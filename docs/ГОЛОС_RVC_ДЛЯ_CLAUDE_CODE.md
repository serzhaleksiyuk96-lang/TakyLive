# Задание для Claude Code: поставить ИИ-смену голоса (RVC) на ПК стримера

Стример хочет менять свой голос в эфире ИИ-голосом — реалистично (как Fish Audio)
и почти без задержки. ПК: Windows, видеокарта **NVIDIA RTX 4060**.
Ставим **deiteris/voice-changer** — ускоренный форк w-okada voice-changer (только RVC).
Говори со стримером по-русски и просто: он не программист.

Цепочка звука:
`микрофон → voice-changer (RVC на видеокарте) → VB-CABLE → OBS / TikTok LIVE Studio`

## Правила

1. Драйверы ставит **сам стример** (VB-CABLE, драйвер NVIDIA): ты даёшь ссылку и говоришь,
   что нажать. Системные настройки звука меняй только с его согласия, объясняя, что и зачем.
2. Качай только с официальных мест: github.com/deiteris/voice-changer (Releases),
   vb-audio.com, nvidia.com, huggingface.co. Ничего не запускай из других источников.
3. Голоса реальных людей без их согласия не ставь и не предлагай (стримеры, блогеры, звёзды) —
   за это могут заблокировать в TikTok. Свой голос, персонажи, голоса с разрешения — можно.
4. Папка установки — без пробелов и русских букв, например `C:\VC`.
5. Ничего не меняй в TakyLive и его данных.

## Шаг 1. Проверка

```powershell
nvidia-smi                    # видна RTX 4060, версия драйвера 528.33 или новее
Get-Volume | Select DriveLetter, SizeRemaining   # нужно 6+ ГБ свободно (лучше SSD)
Get-Command 7z -ErrorAction SilentlyContinue      # 7-Zip нужен для распаковки .zip.001/.002
```

- Драйвер старее 528.33 → попроси стримера обновить через GeForce Experience / NVIDIA App.
- Нет 7-Zip → с разрешения: `winget install -e --id 7zip.7zip`.

## Шаг 2. Скачать и распаковать voice-changer

На странице Releases (последний релиз) нужны **оба** файла:
`voice-changer-windows-amd64-cuda.zip.001` и `voice-changer-windows-amd64-cuda.zip.002`.

```powershell
New-Item -ItemType Directory C:\VC -Force | Out-Null; cd C:\VC
$rel = Invoke-RestMethod https://api.github.com/repos/deiteris/voice-changer/releases/latest
$rel.tag_name
$rel.assets | ? name -like "voice-changer-windows-amd64-cuda.zip.00*" | % {
  Invoke-WebRequest $_.browser_download_url -OutFile $_.name }
& "C:\Program Files\7-Zip\7z.exe" x .\voice-changer-windows-amd64-cuda.zip.001 -oC:\VC\voice-changer
```

Запуск: `C:\VC\voice-changer\...\MMVCServerSIO\MMVCServerSIO.exe`. Первый запуск качает
нужные файлы — окно не закрывать. Потом сам откроется интерфейс в браузере
(`http://127.0.0.1:18888`). Если Windows спросит про брандмауэр — для домашней сети
можно «Отмена», программа работает на этом ПК.

## Шаг 3. VB-CABLE (ставит стример)

Ссылка: https://vb-audio.com/Cable/ → скачать → распаковать → правой кнопкой
`VBCABLE_Setup_x64.exe` → «Запуск от имени администратора» → Install Driver → перезагрузить ПК.
После перезагрузки проверь, что появились устройства «CABLE Input» и «CABLE Output».

## Шаг 4. Голос (модель RVC)

Модель — файл `.pth` (обычно с ним `.index`). Спроси стримера, какой голос он хочет
(персонаж, «низкий брутальный», «девушка», «аниме» и т.п.), помоги найти на huggingface.co
модель с понятной лицензией, скачай в `C:\VC\models\` и загрузи в свободный слот
через интерфейс (кнопка загрузки модели). Можно загрузить 3–5 голосов в разные слоты —
потом TakyLive сможет переключать их по подаркам.

## Шаг 5. Настройка (в интерфейсе voice-changer)

- Режим звука — **серверный (server audio)**: так меньше задержка.
- Вход — микрофон стримера, выход — **CABLE Input**. Драйвер звука — WASAPI, не MME.
- GPU — RTX 4060. F0 Det. — `rmvpe` (или `rmvpe_onnx`).
- **Passthru** выключен (иначе слышен обычный голос).
- **Chunk**: уменьшай, пока звук не начнёт трещать/заикаться, потом чуть увеличь.
  Время **perf** должно быть меньше Chunk; если нет — увеличь Chunk или уменьши Extra
  и Crossfade. После смены Chunk — Stop и Start.
- **Высота (tune/pitch)**: мужской голос → женская модель обычно +12, наоборот −12.
- Треск: в «Панели управления → Звук» частота микрофона и CABLE должна совпадать
  (например, обе 48000 Гц).

Запиши итоговую задержку (видна в интерфейсе) и настройки.

## Шаг 6. OBS / TikTok LIVE Studio (вместе со стримером)

- Микрофон в OBS / Live Studio → **CABLE Output** (обычный микрофон в OBS выключить,
  иначе будет два голоса).
- Чтобы стример слышал себя: в OBS «Расширенные свойства аудио» → мониторинг для CABLE Output.
- Если голос отстаёт от губ на камере — на источник камеры фильтр «Задержка рендера»
  на ту же величину, что задержка голоса.
- Пусть стример запишет 10 секунд в OBS и послушает.

## Шаг 7. Проверка для связки с TakyLive

TakyLive сможет переключать голоса по подаркам через API voice-changer. Проверь, что оно
отвечает с этого ПК (интерфейс voice-changer должен быть запущен):

```powershell
Invoke-RestMethod http://127.0.0.1:18888/info | ConvertTo-Json -Depth 3 | Out-File C:\VC\info.json
# переключить голос на слот 1 и обратно на 0:
Invoke-RestMethod http://127.0.0.1:18888/update_settings -Method Post -Body @{key="modelSlotIndex"; val="1"}
Invoke-RestMethod http://127.0.0.1:18888/update_settings -Method Post -Body @{key="modelSlotIndex"; val="0"}
# обычный голос (без ИИ) и обратно:
Invoke-RestMethod http://127.0.0.1:18888/update_settings -Method Post -Body @{key="passThrough"; val="true"}
Invoke-RestMethod http://127.0.0.1:18888/update_settings -Method Post -Body @{key="passThrough"; val="false"}
```

Убедись на слух, что голос переключается сразу и без треска.

## Отчёт

Создай `C:\VC\ОТЧЁТ_ГОЛОС.md`: версия (tag) voice-changer, версия драйвера NVIDIA,
какие голоса в каких слотах, настройки (Chunk, Extra, Crossfade, F0, pitch), итоговая
задержка, работает ли переключение через API (шаг 7), что не получилось.
Приложи `C:\VC\info.json` без лишнего. Попроси стримера переслать отчёт в чат, где
делается TakyLive.
