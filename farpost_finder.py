import argparse
import html
import json
import re
import socket
import subprocess
import threading
import time
import traceback
import tkinter as tk
import webbrowser
from collections.abc import Callable
from dataclasses import dataclass
from http.cookiejar import CookieJar
from pathlib import Path
from tempfile import gettempdir
from tkinter import messagebox, ttk
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import HTTPCookieProcessor, Request, build_opener


USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/124.0.0.0 Safari/537.36"
)
SITE_ROOT = "https://www.farpost.ru"
DEFAULT_REQUEST_TIMEOUT = 12.0
DEFAULT_TOTAL_TIMEOUT = 45.0
APP_VERSION = "1.1.1"
GITHUB_OWNER = "ClockworkVL"
GITHUB_REPO = "fpst"
GITHUB_LATEST_RELEASE_API = (
    f"https://api.github.com/repos/{GITHUB_OWNER}/{GITHUB_REPO}/releases/latest"
)
APP_LOG_PATH = Path(gettempdir()) / "farpost_finder.log"

CITIES = {
    "Все города": "",
    "Владивосток": "vladivostok",
    "Хабаровск": "khabarovsk",
    "Находка": "nakhodka",
    "Уссурийск": "ussuriisk",
    "Артем": "artem",
    "Арсеньев": "arsenev",
    "Большой Камень": "bolshoi-kamen",
    "Комсомольск-на-Амуре": "komsomolsk-na-amure",
}
CITY_LABEL_BY_SLUG = {slug: label for label, slug in CITIES.items() if slug}

TAG_RE = re.compile(r"<[^>]+>")
SPACE_RE = re.compile(r"\s+")


@dataclass
class Offer:
    title: str
    price_text: str
    price_value: int | None
    city: str
    seller: str
    date_text: str
    url: str


@dataclass
class ReleaseAsset:
    version_tag: str
    asset_name: str
    download_url: str


class GitHubUpdater:
    def __init__(self) -> None:
        self.opener = build_opener(HTTPCookieProcessor(CookieJar()))

    def _request_json(self, url: str, timeout: float = 20.0) -> dict:
        req = Request(
            url,
            headers={
                "User-Agent": USER_AGENT,
                "Accept": "application/vnd.github+json",
            },
            method="GET",
        )
        try:
            with self.opener.open(req, timeout=timeout) as resp:
                payload = resp.read().decode("utf-8", errors="ignore")
            return json.loads(payload)
        except HTTPError as exc:
            if exc.code == 404:
                raise RuntimeError(
                    "На GitHub пока нет опубликованного Release для автообновления."
                ) from exc
            if exc.code == 403:
                raise RuntimeError(
                    "GitHub временно ограничил запросы (HTTP 403). Попробуйте позже."
                ) from exc
            raise RuntimeError(f"GitHub API вернул HTTP {exc.code}.") from exc
        except (URLError, socket.timeout, TimeoutError) as exc:
            raise RuntimeError("Не удалось подключиться к GitHub.") from exc
        except json.JSONDecodeError as exc:
            raise RuntimeError("Некорректный ответ от GitHub API.") from exc

    @staticmethod
    def _version_tuple(raw: str) -> tuple[int, ...] | None:
        match = re.search(r"(\d+(?:\.\d+){0,3})", raw)
        if not match:
            return None
        return tuple(int(x) for x in match.group(1).split("."))

    def get_latest_installer(self) -> ReleaseAsset:
        payload = self._request_json(GITHUB_LATEST_RELEASE_API)
        tag_name = str(payload.get("tag_name", "")).strip()
        assets = payload.get("assets", [])
        if not isinstance(assets, list) or not assets:
            raise RuntimeError(
                "В последнем Release нет файлов. Нужен asset с установщиком .exe."
            )

        def score(asset: dict) -> tuple[int, int]:
            name = str(asset.get("name", "")).lower()
            exe = 1 if name.endswith(".exe") else 0
            installer = 1 if "installer" in name or "setup" in name else 0
            return installer, exe

        candidates = sorted(assets, key=score, reverse=True)
        for item in candidates:
            name = str(item.get("name", ""))
            url = str(item.get("browser_download_url", ""))
            if name.lower().endswith(".exe") and url.startswith("https://"):
                return ReleaseAsset(
                    version_tag=tag_name or "unknown",
                    asset_name=name,
                    download_url=url,
                )
        raise RuntimeError(
            "В Release не найден исполняемый установщик (.exe) для автообновления."
        )

    def has_newer_version(self, release_tag: str) -> bool:
        current = self._version_tuple(APP_VERSION)
        latest = self._version_tuple(release_tag)
        if not current or not latest:
            # If tags are non-standard, still allow user to update manually.
            return True
        return latest > current

    def download_asset(
        self, asset: ReleaseAsset, progress_cb: Callable[[str], None] | None = None
    ) -> Path:
        req = Request(
            asset.download_url,
            headers={"User-Agent": USER_AGENT},
            method="GET",
        )
        target = Path(gettempdir()) / f"{asset.asset_name}"
        try:
            with self.opener.open(req, timeout=30) as resp:
                total_size = int(resp.headers.get("Content-Length", "0") or "0")
                downloaded = 0
                with target.open("wb") as out:
                    while True:
                        chunk = resp.read(1024 * 64)
                        if not chunk:
                            break
                        out.write(chunk)
                        downloaded += len(chunk)
                        if progress_cb:
                            if total_size > 0:
                                percent = int(downloaded * 100 / total_size)
                                progress_cb(f"Скачивание обновления: {percent}%...")
                            else:
                                progress_cb("Скачивание обновления...")
            return target
        except (URLError, socket.timeout, TimeoutError) as exc:
            raise RuntimeError("Не удалось скачать обновление с GitHub.") from exc


class FarpostClient:
    def __init__(self) -> None:
        self.opener = build_opener(HTTPCookieProcessor(CookieJar()))

    @staticmethod
    def _remaining_timeout(deadline: float) -> float:
        left = deadline - time.monotonic()
        if left <= 0:
            raise TimeoutError("Search deadline exceeded.")
        return min(DEFAULT_REQUEST_TIMEOUT, max(1.0, left))

    def _request(
        self,
        url: str,
        method: str = "GET",
        data: bytes | None = None,
        timeout: float = DEFAULT_REQUEST_TIMEOUT,
    ) -> tuple[bytes, str, str]:
        req = Request(
            url,
            data=data,
            headers={"User-Agent": USER_AGENT},
            method=method,
        )
        try:
            with self.opener.open(req, timeout=timeout) as resp:
                body = resp.read()
                ctype = resp.headers.get("Content-Type", "")
                final_url = resp.geturl()
            return body, ctype, final_url
        except HTTPError as exc:
            raise RuntimeError(f"FarPost вернул HTTP {exc.code}.") from exc
        except (URLError, socket.timeout, TimeoutError) as exc:
            raise RuntimeError("FarPost долго не отвечает. Попробуйте ещё раз.") from exc

    @staticmethod
    def _decode(body: bytes, ctype: str) -> str:
        lowered = ctype.lower()
        if "windows-1251" in lowered or "cp1251" in lowered:
            return body.decode("windows-1251", errors="ignore")
        try:
            return body.decode("utf-8")
        except UnicodeDecodeError:
            return body.decode("windows-1251", errors="ignore")

    @staticmethod
    def _clean(text: str) -> str:
        if not text:
            return ""
        no_tags = TAG_RE.sub(" ", text)
        unescaped = html.unescape(no_tags).replace("\xa0", " ")
        return SPACE_RE.sub(" ", unescaped).strip()

    def ensure_verified(
        self,
        city_slug: str,
        deadline: float,
        progress_cb: Callable[[str], None] | None = None,
    ) -> None:
        base = f"{SITE_ROOT}/{city_slug}/" if city_slug else f"{SITE_ROOT}/"
        if progress_cb:
            progress_cb("Проверяю доступ к FarPost...")
        body, ctype, final_url = self._request(
            base, timeout=self._remaining_timeout(deadline)
        )
        page = self._decode(body, ctype)

        if "altcha-widget" in page.lower() or "/verify?" in final_url:
            # FarPost marks this session as human after DELETE /verify in many cases.
            if progress_cb:
                progress_cb("Обхожу антибот-проверку FarPost...")
            self._request(
                f"{SITE_ROOT}/verify",
                method="DELETE",
                timeout=self._remaining_timeout(deadline),
            )
            body2, ctype2, _ = self._request(
                base, timeout=self._remaining_timeout(deadline)
            )
            page2 = self._decode(body2, ctype2)
            if "altcha-widget" in page2.lower():
                raise RuntimeError(
                    "Сайт запросил дополнительную антибот-проверку. "
                    "Повторите попытку чуть позже или с другого IP."
                )

    def search(
        self,
        query: str,
        city_slug: str,
        max_pages: int = 3,
        total_timeout: float = DEFAULT_TOTAL_TIMEOUT,
        progress_cb: Callable[[str], None] | None = None,
    ) -> list[Offer]:
        if not query.strip():
            return []
        deadline = time.monotonic() + max(10.0, total_timeout)
        try:
            self.ensure_verified(city_slug, deadline=deadline, progress_cb=progress_cb)

            base = f"{SITE_ROOT}/{city_slug}/dir" if city_slug else f"{SITE_ROOT}/dir"
            seen_urls: set[str] = set()
            offers: list[Offer] = []

            for page_num in range(1, max_pages + 1):
                if progress_cb:
                    progress_cb(f"Сканирую страницу {page_num}/{max_pages}...")
                params = {"query": query}
                if page_num > 1:
                    params["page"] = str(page_num)
                url = f"{base}?{urlencode(params)}"
                body, ctype, _ = self._request(
                    url, timeout=self._remaining_timeout(deadline)
                )
                text = self._decode(body, ctype)
                items = self._parse_results(text)
                if not items:
                    break

                new_count = 0
                for item in items:
                    if item.url in seen_urls:
                        continue
                    seen_urls.add(item.url)
                    offers.append(item)
                    new_count += 1
                if new_count == 0:
                    break

            if progress_cb:
                progress_cb("Сортирую результаты...")
            offers.sort(key=lambda x: (x.price_value is None, x.price_value or 0))
            return offers
        except TimeoutError as exc:
            raise RuntimeError(
                "Превышено время ожидания ответа FarPost. Попробуйте повторить поиск."
            ) from exc

    def _parse_results(self, text: str) -> list[Offer]:
        rows = re.findall(r"(<tr\s+data-ctr-trackable.*?</tr>)", text, flags=re.I | re.S)
        result: list[Offer] = []
        for row in rows:
            link_m = re.search(r'href="([^"]+\.html[^"]*)"', row, flags=re.I)
            if not link_m:
                continue
            href = html.unescape(link_m.group(1))
            full_url = href if href.startswith("http") else f"{SITE_ROOT}{href}"

            title_m = re.search(
                r'class="[^"]*bulletinLink[^"]*"[^>]*>(.*?)</a>', row, flags=re.I | re.S
            )
            price_m = re.search(r'data-role="price"[^>]*>(.*?)</div>', row, flags=re.I | re.S)
            city_m = re.search(r'bull-delivery__city">([^<]+)</span>', row, flags=re.I)
            seller_m = re.search(r'ellipsis-text__left-side">(.*?)</div>', row, flags=re.I | re.S)
            date_m = re.search(r'<div class="date">(.*?)</div>', row, flags=re.I | re.S)

            title = self._clean(title_m.group(1) if title_m else "")
            price_text = self._clean(price_m.group(1) if price_m else "Цена не указана")
            city = self._clean(city_m.group(1) if city_m else "")
            seller = self._clean(seller_m.group(1) if seller_m else "")
            date_text = self._clean(date_m.group(1) if date_m else "")

            if not city:
                slug_m = re.match(r"/([^/]+)/", href)
                if slug_m:
                    slug = slug_m.group(1).lower()
                    city = CITY_LABEL_BY_SLUG.get(slug, slug)

            normalized_price = price_text.replace(" ", "").replace(",", ".")
            num_m = re.search(r"\d+(?:\.\d+)?", normalized_price)
            price_value = int(float(num_m.group(0)) * 100) if num_m else None

            result.append(
                Offer(
                    title=title or "Без названия",
                    price_text=price_text or "Цена не указана",
                    price_value=price_value,
                    city=city or "Не указан",
                    seller=seller or "Не указан",
                    date_text=date_text or "Не указана",
                    url=full_url,
                )
            )
        return result


class FarpostApp:
    def __init__(self, root: tk.Tk) -> None:
        self.root = root
        self.root.title("FarPost: поиск товаров и цен")
        self.root.geometry("1260x700")
        self._icon_img: tk.PhotoImage | None = None
        self._set_window_icon()
        self.client = FarpostClient()
        self.updater = GitHubUpdater()
        self._search_in_progress = False
        self._update_in_progress = False

        self.query_var = tk.StringVar()
        self.city_var = tk.StringVar(value="Все города")
        self.pages_var = tk.IntVar(value=3)
        self.status_var = tk.StringVar(
            value=f"Версия {APP_VERSION}. Введите запрос и нажмите 'Искать'"
        )

        self._build_ui()

    def _set_window_icon(self) -> None:
        icon_path = Path(__file__).with_name("34.png")
        if not icon_path.exists():
            return
        try:
            self._icon_img = tk.PhotoImage(file=str(icon_path))
            self.root.iconphoto(True, self._icon_img)
        except tk.TclError:
            # Keep default icon if image format is unsupported by local Tk build.
            self._icon_img = None

    def _build_ui(self) -> None:
        controls = ttk.Frame(self.root, padding=10)
        controls.pack(fill="x")

        ttk.Label(controls, text="Товар / запрос:").grid(row=0, column=0, sticky="w")
        query_entry = ttk.Entry(controls, textvariable=self.query_var, width=58)
        query_entry.grid(row=0, column=1, sticky="ew", padx=(8, 14))
        query_entry.focus_set()

        ttk.Label(controls, text="Город:").grid(row=0, column=2, sticky="w")
        city_combo = ttk.Combobox(
            controls,
            textvariable=self.city_var,
            values=list(CITIES.keys()),
            width=24,
            state="readonly",
        )
        city_combo.grid(row=0, column=3, sticky="w", padx=(8, 14))

        ttk.Label(controls, text="Страниц:").grid(row=0, column=4, sticky="w")
        pages_spin = ttk.Spinbox(
            controls, from_=1, to=20, textvariable=self.pages_var, width=5
        )
        pages_spin.grid(row=0, column=5, sticky="w", padx=(8, 14))

        self.search_btn = ttk.Button(controls, text="Искать", command=self.start_search)
        self.search_btn.grid(row=0, column=6, sticky="w")
        self.update_btn = ttk.Button(controls, text="Обновить", command=self.start_update)
        self.update_btn.grid(row=0, column=7, sticky="w", padx=(8, 0))

        controls.columnconfigure(1, weight=1)

        table_frame = ttk.Frame(self.root, padding=(10, 0, 10, 0))
        table_frame.pack(fill="both", expand=True)

        columns = ("price", "title", "city", "seller", "date", "url")
        self.tree = ttk.Treeview(table_frame, columns=columns, show="headings")
        self.tree.heading("price", text="Цена")
        self.tree.heading("title", text="Название")
        self.tree.heading("city", text="Город")
        self.tree.heading("seller", text="Продавец")
        self.tree.heading("date", text="Дата")
        self.tree.heading("url", text="Ссылка")

        self.tree.column("price", width=120, anchor="e")
        self.tree.column("title", width=450)
        self.tree.column("city", width=140)
        self.tree.column("seller", width=170)
        self.tree.column("date", width=145)
        self.tree.column("url", width=500)

        scrollbar = ttk.Scrollbar(table_frame, orient="vertical", command=self.tree.yview)
        self.tree.configure(yscrollcommand=scrollbar.set)
        self.tree.pack(side="left", fill="both", expand=True)
        scrollbar.pack(side="right", fill="y")

        self.tree.bind("<Double-1>", self._open_selected_link)

        status = ttk.Label(self.root, textvariable=self.status_var, padding=10)
        status.pack(fill="x")

    def start_search(self) -> None:
        if self._update_in_progress:
            return
        query = self.query_var.get().strip()
        if not query:
            messagebox.showwarning("Пустой запрос", "Введите название товара для поиска.")
            return

        city_label = self.city_var.get()
        city_slug = CITIES.get(city_label, "")
        max_pages = max(1, min(int(self.pages_var.get()), 20))

        self._search_in_progress = True
        self._sync_action_buttons()
        self.status_var.set("Запускаю поиск по FarPost...")
        self._clear_table()

        thread = threading.Thread(
            target=self._search_worker, args=(query, city_slug, max_pages), daemon=True
        )
        thread.start()

    def _search_worker(self, query: str, city_slug: str, max_pages: int) -> None:
        try:
            offers = self.client.search(
                query=query,
                city_slug=city_slug,
                max_pages=max_pages,
                total_timeout=DEFAULT_TOTAL_TIMEOUT,
                progress_cb=self._set_status_threadsafe,
            )
            self.root.after(0, self._render_offers, offers)
        except Exception as exc:
            err_trace = traceback.format_exc()
            self.root.after(0, self._handle_error, exc, err_trace)

    def start_update(self) -> None:
        if self._search_in_progress or self._update_in_progress:
            return
        self._update_in_progress = True
        self._sync_action_buttons()
        self.status_var.set("Проверяю обновления на GitHub...")
        thread = threading.Thread(target=self._update_worker, daemon=True)
        thread.start()

    def _update_worker(self) -> None:
        try:
            release = self.updater.get_latest_installer()
            if not self.updater.has_newer_version(release.version_tag):
                self.root.after(0, self._finish_update, "У вас уже установлена актуальная версия.")
                return
            self._set_status_threadsafe(
                f"Найдена версия {release.version_tag}. Готовлю скачивание..."
            )
            installer_path = self.updater.download_asset(
                release, progress_cb=self._set_status_threadsafe
            )
            self.root.after(0, self._offer_install_update, installer_path, release)
        except Exception as exc:
            err_trace = traceback.format_exc()
            self.root.after(0, self._handle_update_error, exc, err_trace)

    def _offer_install_update(self, installer_path: Path, release: ReleaseAsset) -> None:
        answer = messagebox.askyesno(
            "Доступно обновление",
            (
                f"Найдена версия {release.version_tag}.\n"
                f"Файл: {release.asset_name}\n\n"
                "Скачать удалось. Запустить установщик сейчас?"
            ),
        )
        if not answer:
            self._finish_update("Обновление скачано. Установщик не запускался.")
            return
        try:
            subprocess.Popen([str(installer_path)])
            self.status_var.set(
                "Установщик обновления запущен. После завершения установки откройте программу снова."
            )
            self._update_in_progress = False
            self._sync_action_buttons()
            self.root.after(800, self.root.destroy)
        except Exception as exc:
            self._handle_update_error(exc)

    def _finish_update(self, message: str) -> None:
        self._update_in_progress = False
        self._sync_action_buttons()
        self.status_var.set(message)

    def _handle_update_error(self, exc: Exception, err_trace: str | None = None) -> None:
        self._update_in_progress = False
        self._sync_action_buttons()
        msg = self._human_error_text(exc, "Не удалось выполнить обновление.")
        self._append_log("UPDATE", exc, err_trace)
        self.status_var.set(msg)
        messagebox.showerror("Обновление", msg)

    def _set_status_threadsafe(self, message: str) -> None:
        self.root.after(0, self.status_var.set, message)

    def _render_offers(self, offers: list[Offer]) -> None:
        self._search_in_progress = False
        self._sync_action_buttons()
        for offer in offers:
            self.tree.insert(
                "",
                "end",
                values=(
                    offer.price_text,
                    offer.title,
                    offer.city,
                    offer.seller,
                    offer.date_text,
                    offer.url,
                ),
            )
        if offers:
            self.status_var.set(f"Найдено объявлений: {len(offers)}. Двойной клик откроет ссылку.")
        else:
            self.status_var.set("По вашему запросу объявления не найдены.")

    def _handle_error(self, exc: Exception, err_trace: str | None = None) -> None:
        self._search_in_progress = False
        self._sync_action_buttons()
        error_text = self._human_error_text(
            exc, "Ошибка поиска. Проверьте интернет и попробуйте снова."
        )
        self._append_log("SEARCH", exc, err_trace)
        self.status_var.set(error_text)
        messagebox.showerror("Ошибка", error_text)

    @staticmethod
    def _human_error_text(exc: Exception | None, fallback: str) -> str:
        if exc is None:
            return fallback
        text = str(exc).strip()
        if text and text != "None":
            return text
        return f"{fallback} [{type(exc).__name__}]"

    @staticmethod
    def _append_log(scope: str, exc: Exception | None, err_trace: str | None) -> None:
        try:
            timestamp = time.strftime("%Y-%m-%d %H:%M:%S")
            with APP_LOG_PATH.open("a", encoding="utf-8") as fh:
                fh.write(f"\n[{timestamp}] {scope}\n")
                fh.write(f"Exception: {repr(exc)}\n")
                if err_trace:
                    fh.write(err_trace)
                    if not err_trace.endswith("\n"):
                        fh.write("\n")
        except Exception:
            # Logging must never crash GUI flow.
            pass

    def _sync_action_buttons(self) -> None:
        self.search_btn.config(
            state="disabled" if self._search_in_progress or self._update_in_progress else "normal"
        )
        self.update_btn.config(
            state="disabled" if self._search_in_progress or self._update_in_progress else "normal"
        )

    def _clear_table(self) -> None:
        for row_id in self.tree.get_children():
            self.tree.delete(row_id)

    def _open_selected_link(self, _event: object) -> None:
        selected = self.tree.selection()
        if not selected:
            return
        values = self.tree.item(selected[0], "values")
        if not values:
            return
        url = values[5]
        if url:
            webbrowser.open(url)


def run_cli(query: str, city: str, pages: int) -> None:
    city_slug = CITIES.get(city, city)
    client = FarpostClient()
    offers = client.search(query=query, city_slug=city_slug, max_pages=pages)
    if not offers:
        print("Объявления не найдены.")
        return
    print(f"Найдено: {len(offers)}")
    for idx, offer in enumerate(offers, start=1):
        price_text = offer.price_text.replace("₽", "руб.")
        print(
            f"{idx:02d}. {price_text} | {offer.title} | "
            f"{offer.city} | {offer.url}"
        )


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Поиск товаров и цен на FarPost с фильтром по городу."
    )
    parser.add_argument("--query", help="Текст запроса. Если не указан, запускается GUI.")
    parser.add_argument(
        "--city",
        default="Все города",
        help=(
            "Город из списка (например, 'Владивосток') "
            "или slug (например, 'vladivostok')."
        ),
    )
    parser.add_argument("--pages", type=int, default=3, help="Сколько страниц выдачи читать.")
    args = parser.parse_args()

    if args.query:
        run_cli(query=args.query, city=args.city, pages=max(1, min(args.pages, 20)))
        return

    root = tk.Tk()
    app = FarpostApp(root)
    root.bind("<Return>", lambda _event: app.start_search())
    root.mainloop()


if __name__ == "__main__":
    main()
