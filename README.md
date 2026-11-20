# Wirehouse

Веб-назва проєкту (логотип і заголовки сторінок); репозиторій, systemd-сервіси й
шляхи лишаються `switch-inventory`.


SNMP-колектор і веб-інтерфейс для інвентаризації світчів, портів, MAC/IP,
серверних кімнат, стійок і кабельних з'єднань.

**Джерело правди — сайт.** Стійки, кабелі, пристрої, імена хостів і карти ведуться
тільки через сайт (кожна зміна — в історії стійок, з відміною). Стара документація
(`Racks.xlsx`, схема оптики «NewsHouse Оптика.drawio», «Newshouse SWs ports.xlsx»)
більше не оновлюється й може бути застарілою: коли вона розходиться із сайтом,
правильним вважається сайт. Скрипти разового імпорту з неї прибрано з репозиторію
(вони є в історії git, коміт до 2026-11-05).

* **Колектор** (`switch-inventory.service`, таймер кожні 5 хв) опитує світчі
  з `config/switches.yaml` по SNMP і пише поточний стан та історію в SQLite.
* **Веб** (`switch-inventory-web.service`, порт 8080) показує Dashboard,
  сторінки світчів, Change History, Rack View і редактор Rack Change.

## Архітектура

Шарова (n-tier) архітектура в одному Python-пакеті `Project`.
Кожен шар імпортує тільки шари **під** собою:

```
            web/  (Flask)           collector/  (SNMP CLI)        ← представлення (PL)
               │                        │
            bll/services  ──►  bll/domain                          ← бізнес-логіка (BLL)
               │                        │
            dal/  (repositories, schema, Database)                 ← доступ до даних (DAL)
               │
            core/  (форматування, MAC)                             ← спільні хелпери
```

| Шар | Що там | Чого там **не** буває |
|---|---|---|
| `core/` | дрібні чисті функції: `normalize_mac`, `format_datetime` | імпортів з інших шарів |
| `dal/` | **увесь SQL**: `Database` (з'єднання, транзакції), `UnitOfWork`, репозиторії, створення/міграції таблиць | бізнес-правил, Flask |
| `bll/domain/` | чисті правила: вендори й панелі портів, які кабелі можна з'єднувати, зайнятість юнітів, сітка Rack View, історія змін | SQL, Flask, I/O, тому їх легко тестувати |
| `bll/services/` | сценарії (use cases): «додати сервер у стійку», «з'єднати порти», «дані для Dashboard». Відкривають одну транзакцію і викликають репозиторії та доменні правила | `request`, `url_for`, HTML |
| `web/` | Flask app factory, blueprints (по одному на розділ), шаблони, статика. Розбирає форми/JSON, викликає сервіс, рендерить шаблон або редірект | SQL, бізнес-правил |
| `collector/` | SNMP (net-snmp), парсери, правила інтерфейсів, FDB, ARP/DNS, CLI. Зберігає дані через репозиторії DAL | Flask |

Помилки бізнес-рівня: сервіси кидають `ValidationError` (повідомлення
показується користувачу) або `NotFoundError` (HTTP 404), а веб-шар
перетворює їх на відповідь.

### Структура

```
web/app.py                     точка входу веб (шлях використовує systemd)
scripts/collector.py           точка входу колектора (шлях використовує systemd)
scripts/backfill_port_changes.py  одноразове перенесення старої історії змін у port_changes
scripts/compact_port_history.py   одноразове видалення повторюваних знімків зі старої port_history
scripts/migrate_timestamps_to_utc.py  одноразовий перерахунок старих міток часу в UTC (--to-local — відкат)
scripts/backup_db.py           резервна копія БД (запускає switch-inventory-backup.timer щоночі)
scripts/restore_db.py          відновлення БД з резервної копії
deploy/systemd/                юніти резервного копіювання
deploy/smb/                    приклади fstab і файлу з паролем для мережевої папки
scripts/db_view.py, db_changes.py   консольні утиліти для перегляду БД
config/switches.yaml           список світчів і SNMP community (не в git; шаблон — switches.yaml.example)

Project/
  settings.py                  шляхи до БД/конфігу, HOST/PORT (можна перевизначити env)
  core/                        text.py, mac.py, xlsx.py
  dal/
    database.py                Database: read() / write() → UnitOfWork
    unit_of_work.py            усі репозиторії на одному з'єднанні
    schema/inventory.py        таблиці колектора (switches, ports, port_history, arp_entries)
    schema/rack.py             таблиці стійок + міграції старих версій
    repositories/              switches, history, arp, racks, equipment, connections, state, trunks, checks
  bll/
    errors.py
    domain/                    vendors, cabling, cable_path, cabling_check, floor_maps, rack_units, rack_board, ports, change_history
    services/                  inventory, rack_view, rack_admin, rack_equipment, cabling, cabling_check
  web/
    __init__.py                create_app()
    helpers.py, assets.py
    blueprints/                dashboard, switches, changes, health, api (/api/version),
                               rack_view, rack_change, rack_equipment, cabling (JSON API), checks
    templates/
      base.html, index.html, switch.html, changes.html, rack_view.html, rack_change.html
      switch/                  частини сторінки світча
      rack/                    макрос render_rack + по шаблону на тип пристрою
      rack_change/             картки та форми бокової панелі редактора
    static/
      css/common/              стилі всіх сторінок (порядок підключення — у web/assets.py)
      css/rack/                стилі стійок, у порядку підключення: rack.css (спільне + бокова панель
                               Rack Change), rack-cisco-4900m.css, rack-view.css (дошка Rack View і відкрита
                               стійка), rack-change.css (масштаб і вузькі екрани Rack Change), cable-path.css,
                               rack-devices.css — останнім: сервери, кабелі, меню порту;
                               у шаблонах inline лишаються лише CSS-змінні та display:none, який читає JS
      css/*.css                стилі окремих сторінок
      js/                      live.js, rack_change.js, rack_view.js, rack_cables.js (лінії кабелів обох
                               сторінок), cable_path.js, floor_maps.js, i18n.js, vendor/htmx
  collector/
    cli.py                     main(): аргументи, цикл по світчах, вивід
    config.py                  YAML
    snmp/                      client (snmpwalk/snmpget), oids, parsers
    interfaces.py              фізичні порти, сортування, швидкість/лінк
    identity.py, fdb.py, ports.py, neighbors.py (LLDP/CDP), arp.py, dns.py, storage.py, report.py
tests/                         unittest: domain, collector, web (на тимчасовій БД)
```

### Куди додавати новий код

* **Нова сторінка** → blueprint у `web/blueprints/`, зареєструвати в
  `blueprints/__init__.py`; дані готує метод сервісу; шаблон у `templates/`.
* **Новий SQL-запит** → метод репозиторію в `dal/repositories/`.
* **Нова таблиця/колонка** → `dal/schema/` (міграція має бути безпечною для
  наявної БД: `CREATE TABLE IF NOT EXISTS`, перевірка колонок перед `ALTER`).
* **Нове правило** (наприклад, новий тип патч-панелі) → `bll/domain/`, з тестом
  у `tests/test_domain.py`.
* **Новий вендор / OID** → `collector/snmp/oids.py`, парсер у
  `collector/snmp/parsers.py`, правило в `collector/interfaces.py`.
* **Стилі** → файл у `static/css/…`, додати в `web/assets.py` у потрібне місце
  (пізніші файли перекривають раніші); кольори — змінні з `common/tokens.css`, а для власних кольорів
  `python3 scripts/theme_colors.py --fix` допише темні значення (`light-dark()`).

## Живі оновлення (без перезавантаження сторінок)

Сторінки не перезавантажуються повністю. Замість цього:

1. **Лічильники версій даних** у таблиці `app_state`: `inventory` збільшує
   колектор наприкінці кожного запуску, `rack` збільшується в тій самій
   транзакції, що й будь-яка зміна в Rack Change (`Database.write(touch="rack")`).
2. **`static/js/live.js`** раз на 20 с (і одразу при поверненні на вкладку)
   питає `/api/version`. Коли лічильник виріс, на `<body>` спрацьовує подія
   `inventory-changed` або `rack-changed`.
3. **Живі блоки** сторінок підписані на ці події через
   [htmx](https://htmx.org) (`static/js/vendor/htmx-2.0.4.min.js`):

   ```html
   <div id="dashboard-live"
        hx-get="{{ request.full_path }}"
        hx-trigger="inventory-changed from:body"
        hx-select="#dashboard-live" hx-swap="outerHTML">
   ```

   Сервер віддає звичайну сторінку, htmx бере з неї лише цей блок і замінює
   його. Прокрутка, текст у пошуку й підказки залишаються.
4. **Пошук** (Dashboard, сторінка світча, Change History): форми з
   `data-live-search` відправляються під час набору тексту, URL оновлюється.
5. **Rack Change**: усе всередині `#rack-change-root` працює через `hx-boost`
   (форми, вкладки Front/Rear, видалення з `hx-confirm`), а з'єднання,
   відключення й нотатки оновлюють лише цей блок. `rack_change.js` і
   `rack_view.js` повторно ініціалізуються після кожної заміни
   (`htmx:afterSettle`). Якщо дані змінив хтось інший, редактор
   оновлюється сам, але не тоді, коли відкрита форма або ви щось вводите.
6. **Rack View** оновлює дошку, але не під час перетягування стійки чи
   перегляду стійки в деталях.

**Новий живий блок:** обгорнути частину шаблону в `div` з унікальним `id` і
атрибутами, як вище. Якщо блок оновлюється після власних дій користувача,
додати в нього `{% include "_versions.html" %}`, щоб `live.js` не оновлював
його вдруге.

**Change History** читає таблицю `port_changes`, яку колектор заповнює в
момент збереження (порівнює новий стан порту з попереднім). Тому сторінка
відкривається за десятки мілісекунд замість ~60 с.

**`port_history`** зберігає рядок порту лише тоді, коли порт з'явився вперше
або змінився хоча б один із device, speed, link, MAC, ifIndex, ifName.
Стан порту на будь-який момент — це його останній рядок до цього моменту
(так працює `scripts/db_changes.py`), поточний стан — таблиця `ports`.
Раніше колектор копіював усі порти кожні 5 хв (~170 тис. рядків на добу);
старі повтори прибирає `scripts/compact_port_history.py`.

**Термін зберігання:** `port_history` і `port_changes` старші за
`RETENTION_DAYS` (30 днів, змінна `SWITCH_INVENTORY_RETENTION_DAYS`, `0` вимикає)
видаляються наприкінці кожного запуску колектора, порціями.

**Розмір файлу БД.** Видалені рядки звільняють сторінки всередині файлу, і SQLite
використовує їх повторно, але сам файл не зменшується. Зменшити його можна командою
`VACUUM`: вона переписує всю базу в новий компактний файл і на цей час
блокує запис (і читання в кінці операції), тож запускати її краще між запусками
колектора:

```bash
python3 -c "import sqlite3; sqlite3.connect('scripts/switch_inventory.db', timeout=60).execute('VACUUM')"
```

## Магістралі між ODF

Магістраль (trunk cable) з'єднує діапазон портів одного ODF з діапазоном
іншого, зазвичай в іншій серверній: напр. NH ODF 1 п.13–24 ↔ MCR «NH ODF»
п.1–10. Додаються в Rack Change, картка **Trunk cables** (ODF цієї стійки,
з якого порту, інший ODF, з якого порту, кількість волокон). Таблиця
`trunk_cables`. ODF, у якого є хоч одна магістраль, правило «однакова назва»
(нижче) не використовує.

Початкове наповнення було зі схеми оптики draw.io (разовий імпорт; схема більше не
ведеться — див. «Джерело правди» на початку).

## Шлях кабелю (оптика)

Для порту ODF або порту з оптичним патчем можна відкрити повний шлях кабелю:
у Rack Change — правий клік по порту → **Show Cable Path**, у Rack View — правий
клік по порту.

* Патч-корд — звичайне з'єднання в редакторі (`port_connections`).
* Магістраль між серверними не вноситься вручну: два ODF з **однаковою назвою**
  (без урахування регістру й зайвих пробілів) у **різних** серверних вважаються
  з'єднаними порт у порт — п1↔п1 … п24↔п24.
* Шлях іде патч → магістраль → патч … і закінчується на світчі/сервері. Якщо
  десь обривається (порт не скомутовано, немає ODF-пари, кілька ODF з такою
  назвою в інших серверних), вікно показує причину.

Логіка — `bll/domain/cable_path.py`, API — `GET /rack/path?type=patch&id=3&port=7`.

**Лінії кабелів** у Rack View і Rack Change (`static/js/rack_cables.js`): наведення на лінію або
її порт підсвічує кабель і обидва порти; клік по лінії залишає підсвітку, доки не клацнути
деінде або не натиснути Esc. Тонку лінію легко влучити: поверх кожної лежить невидима ширша
(`.connection-hit`).

## Меню

Три розділи у шапці. Назви Switches / Racks не клікабельні: їхні списки
відкриваються при наведенні (на телефоні, де наведення немає, — дотиком,
`static/js/nav.js`): **Switches** — Dashboard (`/dashboard`), History (`/changes`, зміни
портів зі SNMP), Check (`/checks`); **Racks** — View (`/rack`), Change
(`/rack-change`), History (`/changes/racks`); **Maps** (`/floor-maps`).
Поточний розділ підсвічено.
Шапка прикріплена до верху вікна (`position: sticky`, `css/common/base.css`): меню, мова, тема й вхід
завжди під рукою. Її висоту `js/nav.js` записує в `--header-height`, щоб «липка» бічна панель Rack Change
і переходи за `#якорями` не ховались під нею. Відкрита стійка й вікно шляху кабелю перекривають шапку.

## Темна тема

Кнопка з місяцем / сонцем у шапці (поруч з УКР / EN) перемикає світлу й темну тему. Вибір
зберігається в cookie `theme` на рік, і сервер одразу малює сторінку в ній (`<html data-theme="dark">`);
поки нічого не вибрано, береться тема системи (скрипт у `base.html`, без білого спалаху).

* Кольори обох тем записані прямо в стилях. Кольори інтерфейсу — змінні з `static/css/common/tokens.css`
  (`var(--surface)`, `var(--text-muted)` …): світлі значення на `:root`, темні під `html[data-theme="dark"]`.
  Власні кольори (обладнання в стійках, мітки, бейджі) записані як `light-dark(<світлий>, <темний>)`;
  браузер вибирає за `color-scheme` (`light` / `dark`, задано в `tokens.css`).
* `scripts/theme_colors.py` знає правила перекладу кольору в темну тему (світлі фони → темні того ж
  відтінку, темний текст → світлий того ж відтінку, насичені кнопки й статуси — без змін; SVG-текст:
  `fill` — текст, `stroke` — обвідка; якщо в правилі текст і фон разом і переведений текст читається
  гірше, лишається оригінальний). `python3 scripts/theme_colors.py` показує кольори без темного значення,
  `--fix` дописує їм `light-dark()`; `tests/test_dark_theme.py` падає, якщо такі є.
* `static/css/dark-fixes.css` — ручні правки (кнопка теми, акценти оптики в стійках, обвідки на карті).
* Контраст тексту в темній темі перевірено за WCAG AA (4,5:1, великий текст 3:1) на всіх основних
  сторінках: 0 порушень.

## Мова інтерфейсу

Українська за замовчуванням, перемикач **УКР / EN** у шапці (cookie `lang` на рік,
`/lang/<code>?next=…` повертає на ту саму сторінку). Логотип завжди «Wirehouse».
Мову за замовчуванням задає `SWITCH_INVENTORY_LANG` (`uk` або `en`); тести
працюють англійською (`tests/__init__.py`), українську перевіряє `tests/test_i18n.py`.

Ключ перекладу — англійський текст. Каталог — `Project/web/translations/uk.py`:
- `MESSAGES` — сталі рядки; множина — список із трьох форм (1 порт / 2 порти / 5 портів);
- `PATTERNS` — регулярні вирази для повідомлень, які сервер складає з даних
  («Cable added: … — …», помилки з назвами); застосовується перший, що збігся повністю;
- `TOKENS` — фрагменти всередині таких повідомлень («(empty)», «U12 rear», «(socket …)»).

У шаблонах: `_("Text")`, `_n("{n} port", "{n} ports", n)`, `{{ message | tr }}` для
текстів від сервера. У JS той самий каталог приходить як `/i18n/<lang>.js`
(`window.I18N`, `static/js/i18n.js`): `t()`, `tn()`, `tm()`. Новий рядок у інтерфейсі —
одразу додати його переклад у `uk.py`, інакше він лишиться англійським.
Назви пристроїв, кімнат, стійок і хостів — дані, вони не перекладаються.

## Головна сторінка

`/` — сюди веде логотип **Wirehouse** (старі `/home` і `/?search=` перенаправляються). Dashboard — на `/dashboard`.

- Пошук по всьому (той самий, що на Dashboard) з підказками під час введення (`/search/suggest`:
  ПК, розетки, стійки, порти; стрілки + Enter) і прикладами запитів, на які можна натиснути.
- Позначка свіжості даних: актуальні (< 10 хв), трохи запізнюються (< 20 хв), застаріли.
- Плитки стану з поясненням; кожна відкриває відповідний список («Порти з помилками» — `/dashboard?errors=1`).
- Розділи Світчі / Стійки / Карти: великі кнопки сторінок, опис сторінки — у підказці при наведенні
  (на сенсорних екранах — під назвою).

## Вхід і права

Переглядати сайт можуть усі. **Будь-яка зміна** (усі POST / PATCH / DELETE: стійки, кабелі,
нотатки, карти, імена хостів, кнопки Cabling Check, Undo) — лише після входу (іконка
**Увійти** праворуч у шапці, `/login`). Без входу:

* кнопок змін просто немає: шаблони не показують їх (`{% if can_edit %}`: Racks → Change у меню
  й на головній, Undo в історії стійок, Add / Delete / Remove у Rack Change, режим Edit на
  картах), а дрібні кнопки з `data-requires-login` (✎ імені хоста, виправлення Check, «+ New map»,
  кнопки розкладки Rack View) ховає `css/common/auth.css`; в історії стійок немає колонки Undo;
* **Rack Change недоступний**: `/rack-change` веде на вхід, `/rack-change/<id>` — у Rack View на
  ту саму стійку. Посилання «відкрити стійку» (історія, Check, пошук) будує `rack_url()`
  (`web/helpers.py`): після входу — Rack Change, без входу — `/rack/<id>?side=&focus=`, що відкриває
  стійку в Rack View (`?room_id=&open=&side=&focus=`, `static/js/rack_view.js`) з підсвіченим портом;
* клік по порту відкритої стійки в Rack View, а також будь-яка POST-форма показують сповіщення «Щоб вносити зміни, увійдіть» з
  кнопкою входу (`static/js/auth.js`, `WirehouseAuth.ensure()`); перетягування стійок і вкладок
  карт вимкнене;
* сервер однаково відмовляє (`web/auth.py`): 401 `{"login_required": true}` і заголовок
  `X-Login-Required` для fetch / htmx, перенаправлення на `/login` для звичайної форми.
  Нова сторінка зі змінами нічого додатково не потребує — достатньо, що зміни йдуть не через GET.

Сесія — підписана cookie Flask (`wirehouse_session`, HttpOnly, SameSite=Lax) на
`SWITCH_INVENTORY_SESSION_HOURS` (12 год). Зміни приймаються лише зі сторінок цього сайту
(заголовок Origin / Referer). Після 10 невдалих спроб входу з однієї адреси за 10 хв вхід
блокується на кілька хвилин. Rack History показує, хто увійшов (`rack_audit.actor_user`).

Користувачі — локальні, файл `config/web_users` (`ім'я:хеш-пароля`, не в git, права 640,
група gitusers). Додати користувача або змінити пароль (сервіс перечитує файл сам, новий
пароль завершує сесії цього користувача в усіх браузерах):

```bash
python3 scripts/set_password.py admin          # спитає пароль
python3 scripts/set_password.py olduser --remove
```

Ключ підпису сесій — `config/secret_key` (створюється сам при першому запуску веб-сервісу) або
`SWITCH_INVENTORY_SECRET_KEY`. Якщо файлу користувачів немає, увійти не може ніхто — сайт лише
для перегляду. Надалі на місце `LocalUsers` (`bll/services/auth.py`) можна поставити перевірку
групи Active Directory (LDAP) — решта коду від цього не залежить.

## Перетягування обладнання між юнітами

У Rack Change світч (SNMP або тимчасовий), сервер, патч-панель чи кабельний органайзер можна перетягнути мишею за заголовок в
інший юніт тієї ж стійки (`static/js/rack_move.js`). Під час перетягування юніти, які пристрій займе,
підсвічені зеленим (вільні або його власні) чи червоним (там інший пристрій або межа стійки); Esc скасовує,
біля краю вікна сторінка прокручується. Кнопки в заголовку (Видалити, Порти 1 / 2, ⚙️ сервера) лишаються кнопками.

**На телефоні / планшеті:** утримати палець на пристрої ~0,4 с (будь-де, крім портів і кнопок — на телефоні
стійка зменшена, заголовок лише кілька пікселів), потім вести пальцем; короткий свайп, як і раніше, гортає
сторінку, дотик нічого не робить. Напис з юнітом — над пальцем; біля країв вікна сторінка (і стійка вбік, якщо
ширша за екран) прокручується. Миша й перо — за заголовок, як і раніше.

Кабелі (і магістралі ODF) лишаються: з'єднання прив'язані до пристрою й порту, а не до юніта.
`POST /rack/<id>/{switch|switch-placeholder|server|patch-panel|cable-organizer}/<id>/move` з `{"rack_unit": верхній U}`
(`bll/services/rack_equipment.py: move_*`; сам пристрій свої юніти не блокує; сервер на всю глибину
перевіряється з обох боків, бо займає юніти і спереду, і ззаду; у БД сервер, панель і органайзер зберігаються за
НИЖНІМ юнітом, світчі — за верхнім). Зміна — в Rack History («… unit 38 → 20», «Switch … moved»), з відміною.
Шаблон позначає юніти `data-unit` / `data-device`, пристрої — `data-move-*`.

## Історія змін стійок і Undo

**Racks → History** (`/changes/racks`) (або посилання **Rack history** у Rack Change):
кожна зміна з Rack Change, Rack View і Cabling Check — хто (користувач, що увійшов,
а також IP клієнта та ім'я ПК з ARP ядра), коли і що саме: «Cable added: …»,
«Note on PP1 p3: … → …», «Server removed: … (Room / Rack, U12 rear)».

* Записують тригери SQLite (`dal/schema/audit.py`): стару й нову версію кожного
  зміненого рядка таблиць стійок, лише поки відкритий запис
  `Database.write(touch="rack")`. Записи колектора в історію не потрапляють.
* **Undo** повертає всі рядки зміни, як були (видалені — з тими самими id,
  разом із портами, кабелями й нотатками), і сам стає записом, який теж можна
  скасувати. Відмовляє, якщо ці самі рядки змінювались пізніше.
* Підключення до порту, де вже є кабель, більше не прибирає його мовчки:
  `POST /rack/connect` повертає 409 зі списком кабелів, а Rack Change питає
  «Replace it?»; лише з `"replace": true` старий кабель знімається.

## Пошук

Пошук на Dashboard шукає не лише поточні порти світчів (IP, MAC, hostname,
Device), а й усе, що внесено вручну: описи портів світчів, патч-панелей і
серверів (розетки, назви ПК), сервери, патч-панелі, тимчасові світчі, стійки,
задокументовані MAC і робочі місця Floor Maps. Для порту видно, куди веде
кабель; **Rack** відкриває стійку з підсвіченим портом (`?focus=<id порту>`),
**Path** — повний шлях кабелю, **Map** — карту з підсвіченим місцем
(`?search=`).

## Експорт кабельного журналу

**Switches → Check → Excel / CSV** (або **Export cable journal** на сторінці світча —
лише цей світч): рядок на кожен порт — стійка/юніт, опис порту, перший кабель
(патч-панель і примітка розетки), куди веде кабель, задокументований пристрій і
MAC, а також що видно зараз: MAC, IP, hostname, сусід LLDP/CDP.
`GET /export/cable-journal.xlsx|csv[?switch_id=]` — лише після входу (без входу кнопок немає, а адреса веде на `/login`); XLSX пишеться без сторонніх
пакетів (`core/xlsx.py`), CSV — UTF-8 з BOM і `;` для Excel.

## VLAN і помилки портів

Колектор на кожному опитуванні читає (`collector/vlans.py`, `collector/port_errors.py`):
- **VLAN порту**: Cisco IOS — CISCO-VTP-MIB / CISCO-VLAN-MEMBERSHIP-MIB (access, trunk з native і
  дозволеними VLAN); інші — Q-BRIDGE-MIB (dot1qPvid і бітові карти VLAN). У Dell OS10 немає dot1qPvid —
  береться VLAN, де порт untagged; MikroTik віддає лише PVID (trunk видно тільки за native VLAN).
  Зміна VLAN — рядок «VLAN» в історії світчів.
- **Лічильники помилок**: ifInErrors, ifOutErrors, dot3StatsFCSErrors (CRC). У `ports` — останні сирі
  значення, у `port_error_events` — на скільки вони зросли з минулого опитування (скидання й переповнення
  ігноруються). Зберігаються стільки ж, скільки історія портів.

Сторінка світча: колонка VLAN, значок «помилки N» і жовтий кут на порті, якщо лічильники зросли за 24 год
(у підказці — CRC / вх / вих). Dashboard: картка «Порти з помилками», помилки по світчах, колонка VLAN у
пошуку; запит `vlan 140` показує всі порти VLAN (і на сторінці світча теж).

## Імена пристроїв

Колонка «Ім'я хоста» (сторінка світча, пошук, підказки) бере ім'я пристрою в такому порядку:
1. **вписане вручну** — олівець ✎ біля пристрою на сторінці світча (`POST /hosts/name`, таблиця
   `host_names`, ключ — MAC, тож ім'я йде за пристроєм на будь-який порт; порожнє ім'я видаляє;
   зміни — в історії стійок, з відміною); жирним;
2. **DNS** (зворотний запит колектора);
3. **з документації**, якщо DNS не знає: документований пристрій із цим MAC, ПК з цим IP на карті,
   сервер / нотатка розетки на іншому кінці задокументованого кабелю, нотатка на порту
   (не для аплінків із багатьма пристроями); курсивом.

## Cabling Check — «Перевірка з'єднань» (документація проти реальності)

**Switches → Check** (`/checks`, Cabling Check) порівнює кабелі, внесені в Rack Change, з тим, що
бачать самі світчі (дані з останнього опитування колектора):

* **Switch-to-switch links** — сусіди LLDP/CDP. *Differs*: кабель задокументовано
  до іншого світча/порту; *Not documented*: світч бачить сусіда, а кабелю немає
  або шлях обривається (напр. на ODF). Якщо обидва порти вільні й світчі
  змонтовані — кнопка **Add cable** додає прямий кабель. Анонси з VLAN-інтерфейсу
  (MikroTik), які чути крізь інші світчі на всіх аплінках, відкидаються.
* **Port descriptions** — ifAlias порту називає інший світч, ніж задокументовано.
* **Another device on the port** («Інший пристрій на порту») — колектор на кожному опитуванні
  порівнює MAC порту з тими, що були на ньому востаннє (`ports.last_mac`, зберігається й поки порт
  погашений), і записує заміну в `port_device_changes`, якщо жодного старого MAC на порту вже немає,
  а є інші (`bll/domain/cabling_check.device_replaced`). Не заміна: пристрій заснув і повернувся;
  поруч з'явився другий (спільний MAC лишився). Випадкові MAC (локально призначені — клієнти
  Wi-Fi, віртуальні інтерфейси) не враховуються, тож точка доступу зі змінними клієнтами — той самий
  пристрій; порти з понад 4 MAC (аплінки) не відстежуються. Блок показує кожен порт один раз —
  останню заміну (було → стало, коли) і скільки замін було за `RETENTION_DAYS`; стільки ж
  зберігаються й записи. Наявну історію (`port_changes`) переносить разово
  `python3 scripts/backfill_device_changes.py` (`--dry-run` — лише порахувати).
* Розділи *Documented devices*, *Active ports without a documented cable*, *Other LLDP / CDP
  neighbours* і *Documented cables with the link down* зі сторінки прибрано (2026-11-09). Звіт (`bll/services/cabling_check.py`) їх
  і далі рахує, а API `/checks/expected-device…`, `/checks/port-name…` лишились.
* Кнопки виправлення (усе потрапляє в Rack History, можна скасувати):
  **Add cable** — прямий кабель між вільними портами; **Complete path** —
  задокументований шлях обривається на вільному порту ODF / патч-панелі в тій
  серверній, де стоїть сусід, → кабель від сусіда до цього порту; **Re-cable** —
  прямий кабель до не того порту того самого світча переноситься на порт, який
  бачить LLDP/CDP (якщо порт зайнятий — питає).
  Кнопки «Remove cable» на сторінці немає (2026-11-09): кабель видаляють у Rack Change.

Сусіди LLDP/CDP також видно в колонці **Neighbour** на сторінці світча.
Колектор: `collector/neighbors.py` (LLDP-MIB, CISCO-CDP-MIB) → таблиця
`port_neighbors`; логіка — `bll/services/cabling_check.py`,
`bll/domain/cabling_check.py`.

## Floor Maps (схеми приміщень)

Вкладка **Floor Maps** — схеми робочих зон (за замовчуванням створюються
`Newsroom` і `АСБ`, можна додати свої через **+ New map**). Порядок вкладок
карт змінюється перетягуванням мишею; перша вкладка відкривається за
посиланням Floor Maps.

* **View** — наведення на робоче місце показує роль ПК, назву ПК, IP, кімнату
  й примітку; пошук підсвічує місця за назвою, IP або роллю; клік по ролі в
  легенді — те саме.
* **Масштаб** — кнопки − / % / + / Fit над картою, Ctrl + коліщатко миші (або
  жест на тачпаді) навколо курсора, клавіші + / − / 0. Збільшену карту можна
  тягнути мишею за порожнє місце. Масштаб запам'ятовується для кожної карти.
* **Edit** — інструменти:
  * **Room** — потягнути мишею для прямокутної кімнати або клікати кути
    (Enter / клік по першому куту — завершити, Esc — скасувати);
  * **Area** — так само малює робочу зону: прозора всередині, пунктирна
    рамка, лежить над кімнатами (напр. група столів). Кімнату й зону можна
    перетворити одну в одну полем **Type**;
  * **Workplace** — клік на порожньому місці ставить робоче місце, справа
    заповнюються роль ПК, назва ПК, IP (перевіряється), примітка; наявні місця
    цим інструментом можна перетягувати;
  * **Phone** / **Wi-Fi** — те саме для телефонів і точок доступу (менший
    круглий значок, підпис праворуч; ролі немає). Тип наявного місця можна
    змінити в полі **Type**;
  * **Select** — перетягувати місця, кімнати й зони (кімната рухається разом
    із зонами й місцями всередині), тягнути сторону кімнати чи зони, щоб
    розширити/звузити її, або кути вибраної;
  * стрілки рухають вибране місце чи кімнату на пів клітинки, Shift + стрілка —
    на 4; Delete видаляє вибране без підтвердження, а **Undo** у повідомленні
    або Ctrl+Z повертає його;
  * **Map settings** — назва, розмір сітки, видалення карти.
* Для місця з IP підказка показує, де ПК підключений зараз: IP → MAC (ARP з
  ядра) → порт світча (FDB), з останнього опитування колектора. MAC видно й на
  аплінках, тому береться порт із найменшою кількістю MAC; якщо їх на порту
  кілька — показується кількість (часто це Wi-Fi точка або некерований світч).
  «Not seen in ARP» — IP зараз не в мережі; «switch port not found» — MAC є,
  але не на опитуваних світчах (`bll/domain/ports.py: locate_ips`).
* Усе зберігається одразу; інші відкриті вкладки оновлюються самі (лічильники
  `maps` і `inventory` у `/api/version`).

* **Розетка** (поле *Wall socket*, напр. `2-19`): шукається на патч-портах — за
  міткою порту або «socket 2-19» у нотатці (так записав імпорт журналу;
  `2-07` = `2-7`). Підказка й панель показують шлях розетка → патч-порт →
  порт світча і чи ПК зараз саме там (інакше — попередження). Без розетки
  пропонується розетка за портом, де видно ПК, або за ім'ям ПК у нотатках
  патч-портів; **Map settings → Fill … wall sockets** заповнює всі такі разом.
* **Dante IP** — друга мережева карта ПК (аудіомережа Dante, напр. в АСБ):
  підказка й панель показують для неї окремо порт Dante-світча; пошук на карті
  й на Dashboard знаходить ПК за будь-якою з двох адрес.
* ПК без IP знаходиться на порту за MAC, задокументованим для пристрою з тим
  самим ім'ям (Cabling Check / журнал).

Таблиці: `floor_maps`, `floor_map_rooms` (`room_type`: room / area; кути — JSON у клітинках сітки),
`floor_map_workplaces` (`device_type`: pc / phone / wifi). API — `/floor-maps/api/...` (`web/blueprints/floor_maps.py`).

## Час

Усі мітки часу в базі зберігаються в **UTC з явним зсувом**:
`2026-10-14T14:45:59+00:00` (`Project/core/text.py: now_iso()`). Такі рядки
сортуються й порівнюються як текст і не плутаються під час переходу на зимовий
чи літній час (година 03:00–04:00 наприкінці жовтня повторюється).

На сторінках і в консольних утилітах час показується в поясі
`SWITCH_INVENTORY_TIMEZONE` (за замовчуванням `Europe/Kyiv`) через
`format_datetime()`. Нове поле з часом: записувати `now_iso()`, показувати
`format_datetime()`.

Значення без зсуву (до міграції) вважаються місцевим часом;
`scripts/migrate_timestamps_to_utc.py` перераховує їх у UTC (можна запускати
повторно; `--to-local` повертає назад).

## Запуск

```bash
# конфіг (один раз): скопіювати шаблон і вписати світчі та SNMP community
cp config/switches.yaml.example config/switches.yaml

# веб локально на копії БД
SWITCH_INVENTORY_DB=/tmp/copy.db SWITCH_INVENTORY_PORT=8081 python3 web/app.py

# колектор вручну
python3 scripts/collector.py --config config/switches.yaml
python3 scripts/collector.py --json        # вивід у JSON
python3 scripts/collector.py --csv out.csv # вивід у CSV
```

Змінні оточення: `SWITCH_INVENTORY_DB`, `SWITCH_INVENTORY_CONFIG`,
`SWITCH_INVENTORY_HOST`, `SWITCH_INVENTORY_PORT`, `SWITCH_INVENTORY_USERS_FILE`,
`SWITCH_INVENTORY_SECRET_KEY` (або `SWITCH_INVENTORY_SECRET_KEY_FILE`), `SWITCH_INVENTORY_SESSION_HOURS`.

## Тести

```bash
python3 -m unittest discover -s tests -t .
```

Тільки стандартна бібліотека + Flask і PyYAML, які вже є на сервері.

## Резервні копії

Щоночі о 02:30 `switch-inventory-backup.timer` запускає `scripts/backup_db.py`
від користувача `administrator`:

1. цілісна копія бази «на ходу» (SQLite backup API, сайт і колектор не
   зупиняються, вміст `-wal` теж потрапляє в копію);
2. `PRAGMA integrity_check` копії; пошкоджена копія не зберігається;
3. стиснення `zstd` (~8 МБ), файл `switch_inventory-РРРР-ММ-ДД_ГГХХСС.db.zst`, права 600;
4. збереження в `/var/backups/switch-inventory`, далі копія в мережеву папку,
   якщо її налаштовано;
5. ротація в обох місцях: 14 щоденних, 8 щотижневих, 6 щомісячних копій.

Якщо мережева папка недоступна, локальна копія все одно зберігається, а запуск
позначається як невдалий (`systemctl --failed`).

### Встановлення (разово, через sudo)

```bash
sudo install -d -o administrator -g administrator -m 750 /var/backups/switch-inventory
sudo cp /opt/switch-inventory/deploy/systemd/switch-inventory-backup.{service,timer} /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now switch-inventory-backup.timer

# перша копія одразу, без очікування ночі
sudo systemctl start switch-inventory-backup.service
journalctl -u switch-inventory-backup.service -n 20
ls -la /var/backups/switch-inventory
```

### Мережева папка (SMB)

1. На файловому сервері: папка, напр. `\\FILESERVER\Backups\switch-inventory`, і
   службовий обліковий запис лише з правом запису в неї (бажано з тіньовими копіями).
2. На цьому сервері:

```bash
sudo install -d -m 700 /etc/switch-inventory
sudo install -m 600 /opt/switch-inventory/deploy/smb/smb-backup.cred.example /etc/switch-inventory/smb-backup.cred
sudo nano /etc/switch-inventory/smb-backup.cred         # логін, пароль, домен
sudo install -d /mnt/switch-inventory-backup
cat /opt/switch-inventory/deploy/smb/fstab.example     # рядок для fstab
sudo nano /etc/fstab                                   # додати рядок, підставити адресу
sudo systemctl daemon-reload
sudo systemctl restart remote-fs.target
ls /mnt/switch-inventory-backup                        # має підключитися
```

3. У `/etc/systemd/system/switch-inventory-backup.service` розкоментувати
   `SWITCH_INVENTORY_BACKUP_REMOTE_DIR` і `ReadWritePaths=-/mnt/switch-inventory-backup`, далі
   `sudo systemctl daemon-reload && sudo systemctl start switch-inventory-backup.service`.

### Відновлення

```bash
python3 scripts/restore_db.py --list          # доступні копії
python3 scripts/restore_db.py /var/backups/switch-inventory/switch_inventory-2026-10-14_023000.db.zst
```

Перед відновленням поточна база автоматично зберігається як ще одна копія.
Сервіси зупиняти не потрібно; відкриті сторінки оновляться самі. Раз на місяць
варто перевірити, що копія відновлюється, наприклад у тимчасовий файл:
`python3 scripts/restore_db.py ФАЙЛ --db /tmp/check.db --dir /tmp --yes`.

## Адреса і nginx

Сайт відкривається як `http://wirehouse` (A-запис `wirehouse` → `10.13.40.6` у
DNS домену `newshouse.lan`), а також за IP. nginx на порту 80
(`deploy/nginx/wirehouse.conf`, встановлення — у коментарі файлу) передає запити
застосунку на `127.0.0.1:8080`; старий адрес `http://10.13.40.6:8080` теж працює.

Історія змін стійок бере адресу браузера з `X-Real-IP`, який ставить nginx, —
лише для запитів із самого сервера (`web/__init__.py: client_ip`), тож напряму
на `:8080` підмінити адресу не можна. Скрипти на сервері без nginx
підписуються «this server (script)».

### HTTPS

`https://wirehouse` — сертифікат власного CA Wirehouse (`deploy/tls/make_certs.sh`,
файли в `/etc/ssl/wirehouse`, ключі — лише root). Поки корінь не встановлено на
ПК, браузер попереджає «підключення не захищене»; http теж працює, без
перенаправлення.

* Корінь CA: `http://wirehouse/wirehouse-ca.crt`. Встановити на ПК: двічі
  клікнути → *Install Certificate* → *Local Machine* → *Trusted Root
  Certification Authorities*; для всіх — GPO: *Computer Configuration → Policies →
  Windows Settings → Security Settings → Public Key Policies → Trusted Root
  Certification Authorities → Import*.
* CA обмежений іменами (`wirehouse`, `wirehouse.newshouse.lan`, `nh-wirehouse…`,
  IP `10.13.40.6`): навіть викраденим ключем не підробити інші сайти.
* Сертифікат сервера дійсний до 02.2029: `sudo deploy/tls/make_certs.sh --renew`,
  далі `sudo systemctl reload nginx`. CA — до 2036.
* Коли корінь роздано всім — увімкнути перенаправлення http → https (рядок у
  `deploy/nginx/wirehouse.conf`).
* Сертифікат від CA домену (AD CS), якщо з'явиться, ставиться замість
  `server-chain.crt` / `server.key`.

## Деплой

Шляхи точок входу не змінилися, тож systemd-юніти правити не потрібно:

```bash
cd /opt/switch-inventory
git pull
python3 -m unittest discover -s tests -t .
sudo systemctl restart switch-inventory-web.service
# колектор підхопить новий код при наступному запуску таймера
```

Посилання на CSS / JS мають `?v=<відбиток>` — хеш вмісту `web/static/` і `web/translations/`,
який рахується під час запуску веб-сервісу (`web/assets.py`). Змінився будь-який файл — після
перезапуску змінюється й версія, і браузери самі завантажують нові файли (Ctrl+F5 не потрібен).

Одноразово після оновлення з версії без `port_changes`: дочекатися першого
запуску нового колектора і перенести стару історію змін (запит читає весь
`port_history`, ~1 хв, БД при цьому не блокується):

```bash
python3 scripts/backfill_port_changes.py
```
"# wirehouse-clone" 
