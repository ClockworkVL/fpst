# FarPost Finder

Программа ищет товары на `farpost.ru`, собирает объявления и цены, и умеет фильтровать результаты по городу.

## Запуск без установки

GUI:

```powershell
pythonw run_farpost_gui.pyw
```

CLI:

```powershell
python farpost_finder.py --query "totachi 5w30 synthetic" --city "Владивосток" --pages 2
```

## Установщик

Готовый файл установщика:

`G:\pjkt\fpst\FarpostFinder_Installer.exe`

Установщик:
- ставит программу в `%LocalAppData%\Programs\Farpost Finder`;
- создаёт ярлык в меню `Пуск`;
- по выбору создаёт ярлык на рабочем столе;
- корректно удаляется через «Установленные приложения».

## Кнопка обновления

В приложении есть кнопка `Обновить`:
- проверяет последний Release в GitHub: `ClockworkVL/fpst`;
- скачивает `FarpostFinder_Installer.exe`;
- предлагает сразу запустить установщик.

## Пересборка установщика

```powershell
build_installer.bat
```
