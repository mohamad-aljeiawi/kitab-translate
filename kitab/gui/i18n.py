"""Every word the window shows, in English and Arabic.

Kept in one table rather than Qt's .ts/.qm pipeline: two languages do not need a
compiler step, and a missing key fails loudly in tests instead of silently showing
the source string. Wording is written for each language, not translated word for
word, so the Arabic column is what an Arabic reader would expect to see.

Messages that come from the translation pipeline itself (errors, log lines) stay
in English: they are for diagnosis, and a search engine finds them as written.
"""

from __future__ import annotations

from PySide6.QtCore import QLocale

LANGUAGES = ("en", "ar")
_current = "en"


def set_language(code: str) -> None:
    global _current
    _current = code if code in LANGUAGES else "en"


def language() -> str:
    return _current


def is_rtl() -> bool:
    return _current == "ar"


def resolve(preference: str) -> str:
    """Turn the Settings choice (auto, en, ar) into a language to show."""
    if preference in LANGUAGES:
        return preference
    return "ar" if QLocale.system().language() == QLocale.Language.Arabic else "en"


#: Right-to-left mark. An Arabic sentence that opens with a Latin word ("EPUB
#: للهواتف…") would otherwise be laid out left to right, scrambling its word order.
_RLM = "‏"
#: Page ranges inside Arabic sentences ("1-5,12") are wrapped in U+2066 ... U+2069,
#: a left-to-right isolate, or the bidi algorithm reorders them into "5,12-1".
#: Left-to-right mark, used to keep a file extension attached to its name.
_LRM = "‎"


def tr(key: str, **values) -> str:
    text = _STRINGS[key][0 if _current == "en" else 1]
    text = text.format(**values) if values else text
    return _RLM + text if _current == "ar" else text


def file_name(name: str) -> str:
    """A file name that reads naturally whatever script it is in.

    In "علم المناعة 2.pdf" the bidi algorithm folds ".pdf" into the Arabic run and
    shows "pdf.2 علم المناعة". A left-to-right mark before the extension keeps it
    whole and at the end of the name.
    """
    stem, dot, suffix = name.rpartition(".")
    if not dot or not any("֐" <= ch <= "ࣿ" for ch in stem):
        return name
    return f"{stem}{_LRM}.{suffix}"


def plural(key: str, n: int) -> str:
    """A count with its noun, grammatical in both languages."""
    forms = _PLURALS[key]
    if _current == "en":
        return forms["en"][0 if n == 1 else 1].format(n=n)
    ar = forms["ar"]
    if n == 0:
        form = ar["zero"]
    elif n == 1:
        form = ar["one"]
    elif n == 2:
        form = ar["two"]
    elif 3 <= n % 100 <= 10:
        form = ar["few"]
    elif 11 <= n % 100 <= 99:
        form = ar["many"]
    else:
        form = ar["other"]
    return _RLM + form.format(n=n)


def duration(seconds: float) -> str:
    seconds = int(max(0, seconds))
    minutes, secs = divmod(seconds, 60)
    hours, minutes = divmod(minutes, 60)
    if hours:
        return tr("time.hm", h=hours, m=minutes)
    if minutes:
        return tr("time.ms", m=minutes, s=secs)
    return tr("time.s", s=secs)


# fmt: off
_STRINGS: dict[str, tuple[str, str]] = {
    # ---- window and navigation
    "app.title": ("Kitab — translate books into Arabic", "كتاب — ترجمة الكتب إلى العربية"),
    "nav.translate": ("Translate", "ترجمة"),
    "nav.jobs": ("My translations", "ترجماتي"),
    "nav.settings": ("Settings", "الإعدادات"),
    "switch.on": ("On", "مفعّل"),
    "switch.off": ("Off", "معطّل"),

    # ---- Translate page
    "translate.title": ("Translate a book", "ترجمة كتاب"),
    "books.title": ("Books", "الكتب"),
    "books.drop": ("Drag books here", "اسحب الكتب إلى هنا"),
    "books.drop_or": ("or", "أو"),
    "books.choose": ("Choose files", "اختر ملفات"),
    "books.add_more": ("Add more", "إضافة المزيد"),
    "books.clear": ("Remove all", "إزالة الكل"),
    "books.supported": (
        "PDF, EPUB, HTML, Markdown or plain text, written in English or Japanese",
        "ملفات PDF أو EPUB أو HTML أو Markdown أو نص عادي، مكتوبة بالإنجليزية أو اليابانية",
    ),
    "book.remove": ("Remove from the list", "إزالة من القائمة"),
    "book.checking": ("Checking the file…", "جارٍ فحص الملف…"),
    "book.pdf": ("PDF · {pages} pages", "PDF · عدد الصفحات: {pages}"),
    "book.scanned": (
        "Scanned PDF · {pages} pages · the text will be read from the page images",
        "PDF ممسوح ضوئيًا · عدد الصفحات: {pages} · سيُقرأ النص من صور الصفحات",
    ),
    "book.epub": ("E-book (EPUB)", "كتاب إلكتروني (EPUB)"),
    "book.html": ("Web page (HTML)", "صفحة ويب (HTML)"),
    "book.markdown": ("Markdown text", "نص Markdown"),
    "book.text": ("Plain text", "نص عادي"),
    "book.unreadable": ("This file can't be opened", "تعذّر فتح هذا الملف"),
    "dialog.choose_books": ("Choose books", "اختر الكتب"),
    "dialog.books": ("Books", "الكتب"),
    "dialog.all_files": ("All files", "كل الملفات"),
    "dialog.choose_folder": ("Choose where to save", "اختر مكان الحفظ"),

    "group.translation": ("Translation", "الترجمة"),
    "engine.title": ("Translation service", "خدمة الترجمة"),
    "engine.desc": (
        "Google is free. The others give better results and need a key, added in Settings.",
        "خدمة Google مجانية. أما البقية فتعطي نتائج أفضل وتحتاج إلى مفتاح تضيفه من الإعدادات.",
    ),
    "engine.google": ("Google Translate (free)", "ترجمة Google (مجانية)"),
    "engine.openai": ("OpenAI", "OpenAI"),
    "engine.deepseek": ("DeepSeek", "DeepSeek"),
    "engine.openailiked": ("Another compatible server", "خادم متوافق آخر"),
    "model.title": ("Model", "النموذج"),
    "model.desc": ("Leave empty to use {model}", "اتركه فارغًا لاستخدام {model}"),
    "model.desc_plain": (
        "Leave empty to use the service's default",
        "اتركه فارغًا لاستخدام النموذج الافتراضي للخدمة",
    ),
    "thinking.title": ("Thinking level", "مستوى التفكير"),
    "thinking.desc": (
        "For reasoning models such as GPT-6 Luna. More thinking is slower and costs more, "
        "but can help with difficult text.",
        "لنماذج الاستدلال مثل GPT-6 Luna. التفكير الأطول أبطأ وأعلى تكلفة، "
        "لكنه يفيد مع النصوص الصعبة.",
    ),
    "thinking.default": ("Model default", "حسب النموذج"),
    "thinking.none": ("Off (fastest)", "بدون تفكير (الأسرع)"),
    "thinking.minimal": ("Minimal", "أدنى حد"),
    "thinking.low": ("Low", "منخفض"),
    "thinking.medium": ("Medium", "متوسط"),
    "thinking.high": ("High", "مرتفع"),
    "thinking.xhigh": ("Very high", "مرتفع جدًا"),
    "thinking.max": ("Maximum", "أقصى حد"),
    "source.title": ("Book language", "لغة الكتاب"),
    "source.desc": ("The translation is always into Arabic", "الترجمة تكون دائمًا إلى العربية"),
    "source.auto": ("Detect automatically", "اكتشاف تلقائي"),
    "source.en": ("English", "الإنجليزية"),
    "source.ja": ("Japanese", "اليابانية"),

    "group.result": ("Result", "النتيجة"),
    "output.title": ("Save to", "مكان الحفظ"),
    "output.same": ("The same folder as each book", "نفس مجلد كل كتاب"),
    "output.change": ("Change…", "تغيير…"),
    "output.reset": ("Save next to each book", "الحفظ بجانب كل كتاب"),
    "formats.title": ("File types", "أنواع الملفات"),
    "formats.desc": (
        "EPUB for phones and e-readers, PDF for printing",
        "EPUB للهواتف وأجهزة القراءة، وPDF للطباعة",
    ),

    "group.more": ("More options", "خيارات إضافية"),
    "more.desc": ("Most books don't need these", "معظم الكتب لا تحتاج إليها"),
    "pages.title": ("Pages", "الصفحات"),
    "pages.desc": (
        "PDF only. Try a few pages first, for example 1-10 or 1-5,12",
        "لملفات PDF فقط. جرّب بضع صفحات أولًا، مثل ⁦1-10⁩ أو ⁦1-5,12⁩",
    ),
    "pages.all": ("All pages", "كل الصفحات"),
    "pages.invalid": (
        "Use page numbers and ranges, for example 1-10,15",
        "استخدم أرقام الصفحات والنطاقات، مثل ⁦1-10,15⁩",
    ),
    "glossary.title": ("Keep terms consistent", "توحيد المصطلحات"),
    "glossary.desc": (
        "Translates repeated terms the same way across the whole book",
        "يترجم المصطلحات المتكررة بالطريقة نفسها في الكتاب كله",
    ),
    "figures.title": ("Translate text inside images", "ترجمة النص داخل الصور"),
    "figures.desc": (
        "Reads the labels in diagrams and adds an Arabic caption under each one",
        "يقرأ التسميات في الرسوم ويضيف تحت كل رسم شرحًا بالعربية",
    ),
    "bilingual.title": ("Keep the original text", "الإبقاء على النص الأصلي"),
    "bilingual.desc": (
        "Shows the original under each translated paragraph, to check the translation",
        "يعرض النص الأصلي تحت كل فقرة مترجمة، لمراجعة الترجمة",
    ),
    "ocr.title": ("Always read text from images (OCR)", "قراءة النص من الصور دائمًا (OCR)"),
    "ocr.desc": (
        "Use when a PDF's text comes out garbled. Scanned PDFs do this on their own.",
        "استخدمه إذا ظهر نص ملف PDF مشوّهًا. ملفات PDF الممسوحة ضوئيًا تفعل ذلك تلقائيًا.",
    ),
    "start.button": ("Start translating", "ابدأ الترجمة"),
    "start.none": ("Add a book to start", "أضف كتابًا للبدء"),
    "start.no_format": ("Choose at least one file type", "اختر نوع ملف واحدًا على الأقل"),

    "nokey.title": ("Add a key first", "أضف مفتاحًا أولًا"),
    "nokey.body": (
        "{engine} needs an API key. You can add it in Settings.",
        "تحتاج خدمة {engine} إلى مفتاح API، ويمكنك إضافته من الإعدادات.",
    ),
    "nokey.open": ("Open Settings", "فتح الإعدادات"),
    "nobrowser.title": ("The PDF may not be created", "قد لا يُنشأ ملف PDF"),
    "nobrowser.body": (
        "Making a PDF needs Edge, Chrome or Chromium. The EPUB will be created either way.",
        "يتطلب إنشاء ملف PDF وجود Edge أو Chrome أو Chromium. سيُنشأ ملف EPUB في كل الأحوال.",
    ),
    "queued.title": ("Started", "بدأت الترجمة"),
    "busy.title": ("Already being translated", "قيد الترجمة بالفعل"),

    # ---- My translations page
    "jobs.title": ("My translations", "ترجماتي"),
    "jobs.summary": (
        "{running} translating · {waiting} waiting · {done} finished",
        "قيد الترجمة: {running} · في الانتظار: {waiting} · مكتملة: {done}",
    ),
    "jobs.limit": (
        "Up to {n} at a time. You can change this in Settings.",
        "حتى {n} في الوقت نفسه، ويمكنك تغيير ذلك من الإعدادات.",
    ),
    "jobs.clear": ("Clear finished", "مسح المكتملة"),
    "jobs.empty.title": ("No translations yet", "لا توجد ترجمات بعد"),
    "jobs.empty.body": (
        "Books you translate will appear here, with their progress.",
        "ستظهر هنا الكتب التي تترجمها، مع مدى تقدّمها.",
    ),
    "jobs.empty.go": ("Translate a book", "ترجمة كتاب"),

    "state.queued": ("Waiting for its turn", "في انتظار دوره"),
    "state.stopping": ("Stopping…", "جارٍ الإيقاف…"),
    "state.done": ("Finished", "اكتملت"),
    "state.failed": ("Didn't finish", "لم تكتمل"),
    "state.cancelled": ("Stopped", "أُوقفت"),
    "stage.starting": ("Starting…", "جارٍ البدء…"),
    "stage.extract": ("Reading the book", "قراءة الكتاب"),
    "stage.ocr": ("Reading scanned pages", "قراءة الصفحات الممسوحة"),
    "stage.glossary": ("Collecting key terms", "جمع المصطلحات"),
    "stage.translate": ("Translating", "الترجمة"),
    "stage.rebuild": ("Putting the book together", "تجميع الكتاب"),
    "stage.epub": ("Creating the EPUB", "إنشاء ملف EPUB"),
    "stage.pdf": ("Creating the PDF", "إنشاء ملف PDF"),
    "progress.of": ("{done} of {total}", "{done} من {total}"),
    "job.via": ("with {engine}", "عبر {engine}"),
    "job.resume_hint": (
        "Continue picks up where it stopped.",
        "زر «متابعة» يكمل من حيث توقفت.",
    ),
    "job.cancelled_before": ("Cancelled before it started", "أُلغيت قبل أن تبدأ"),
    "job.crashed": (
        "The translation stopped unexpectedly. Open Details to see why.",
        "توقفت الترجمة بشكل غير متوقع. افتح «التفاصيل» لمعرفة السبب.",
    ),
    "job.parts": ("Parts translated: {done} of {total}", "الأجزاء المترجمة: {done} من {total}"),
    "job.kept": ("{n} kept in the original language", "بقي منها بلغته الأصلية: {n}"),
    "job.warnings": ("{n} warnings — see Details", "تنبيهات: {n} — راجع «التفاصيل»"),

    "action.cancel": ("Cancel", "إلغاء"),
    "action.stop": ("Stop", "إيقاف"),
    "action.open_book": ("Open book", "فتح الكتاب"),
    "action.retry": ("Try again", "إعادة المحاولة"),
    "action.continue": ("Continue", "متابعة"),
    "action.more": ("More actions", "إجراءات أخرى"),
    "action.details": ("Details", "التفاصيل"),
    "action.show_folder": ("Show in folder", "إظهار في المجلد"),
    "action.remove": ("Remove from list", "إزالة من القائمة"),
    "details.title": ("Details: {name}", "التفاصيل: {name}"),
    "details.empty": ("Nothing has been recorded yet.", "لم يُسجَّل شيء بعد."),
    "details.copy": ("Copy", "نسخ"),
    "details.copied": ("Copied", "تم النسخ"),
    "details.close": ("Close", "إغلاق"),

    "quit.title": ("Stop translating and quit?", "إيقاف الترجمة والخروج؟"),
    "quit.body": (
        "Books still in progress: {n}. They will stop now, and each one can continue "
        "from the same point next time.",
        "كتب قيد الترجمة: {n}. ستتوقف الآن، ويمكن متابعة كل منها لاحقًا من النقطة نفسها.",
    ),
    "quit.yes": ("Stop and quit", "إيقاف والخروج"),
    "quit.no": ("Keep translating", "متابعة الترجمة"),

    # ---- Settings page
    "settings.title": ("Settings", "الإعدادات"),
    "group.general": ("General", "عام"),
    "lang.title": ("Language", "اللغة"),
    "lang.desc": ("The language of this app", "لغة واجهة التطبيق"),
    "lang.auto": ("Use the system language", "لغة النظام"),
    "theme.title": ("Appearance", "المظهر"),
    "theme.auto": ("Use the system setting", "حسب النظام"),
    "theme.light": ("Light", "فاتح"),
    "theme.dark": ("Dark", "داكن"),

    "group.services": ("Translation services", "خدمات الترجمة"),
    "services.where": (
        "Keys stay on this computer, in {where}.",
        "تبقى المفاتيح على هذا الجهاز فقط، في {where}.",
    ),
    "where.windows": ("Windows Credential Manager", "مدير بيانات الاعتماد في Windows"),
    "where.keyring": ("the system keyring", "سلسلة مفاتيح النظام"),
    "where.kwallet": ("KWallet", "KWallet"),
    "where.file": (
        "a file only you can read, because no system keyring was found",
        "ملف لا يقرؤه غيرك، لعدم وجود سلسلة مفاتيح في النظام",
    ),
    "service.google.desc": ("Free, no key needed", "مجانية ولا تحتاج إلى مفتاح"),
    "service.openailiked.desc": (
        "Ollama, LM Studio, vLLM or any server with an OpenAI-style API",
        "Ollama أو LM Studio أو vLLM أو أي خادم بواجهة مثل OpenAI",
    ),
    "service.status.ready": ("Key saved", "المفتاح محفوظ"),
    "service.status.missing": ("Needs a key", "يحتاج إلى مفتاح"),
    "service.status.optional": ("Ready", "جاهزة"),
    "service.key": ("API key", "مفتاح API"),
    "service.key.required": (
        "Get one from your account on the service's website",
        "احصل عليه من حسابك في موقع الخدمة",
    ),
    "service.key.optional": ("Only if your server asks for one", "فقط إذا طلبه الخادم"),
    "service.key.placeholder": ("Paste your key", "الصق المفتاح هنا"),
    "service.model": ("Default model", "النموذج الافتراضي"),
    "service.model.desc": (
        "Used unless you choose another when translating. Empty means {model}.",
        "يُستخدم ما لم تختر غيره عند الترجمة. تركه فارغًا يعني {model}.",
    ),
    "service.url": ("Server address", "عنوان الخادم"),
    "service.url.desc": (
        "Change only for a proxy or your own server. Empty means {url}.",
        "غيّره فقط عند استخدام وسيط أو خادمك الخاص. تركه فارغًا يعني {url}.",
    ),

    "group.speed": ("Speed", "السرعة"),
    "parallel.title": ("Books at the same time", "عدد الكتب في الوقت نفسه"),
    "parallel.desc": (
        "Scanned books use a lot of processing power; 2 is a good limit",
        "الكتب الممسوحة ضوئيًا تستهلك المعالج كثيرًا، والرقم 2 حد مناسب",
    ),
    "requests.title": ("Requests at once, per book", "الطلبات المتزامنة لكل كتاب"),
    "requests.desc": (
        "Higher is faster on a paid plan. Lower it if the service starts refusing requests.",
        "القيمة الأعلى أسرع مع الخطط المدفوعة. خفّضها إذا بدأت الخدمة برفض الطلبات.",
    ),
    "requests.auto": ("Automatic", "تلقائي"),
    "pagesize.title": ("PDF page size", "حجم صفحة PDF"),
    "pagesize.desc": ("A5 is a common book size", "A5 حجم شائع للكتب"),

    "group.storage": ("Storage", "التخزين"),
    "store.settings": ("Settings folder", "مجلد الإعدادات"),
    "store.open": ("Open", "فتح"),
    "store.work": ("Temporary files", "الملفات المؤقتة"),
    "store.work.desc": (
        "Let stopped translations continue where they left off",
        "تتيح للترجمات المتوقفة أن تكمل من حيث توقفت",
    ),
    "store.delete": ("Delete", "حذف"),
    "store.confirm.title": ("Delete temporary files?", "حذف الملفات المؤقتة؟"),
    "store.confirm.body": (
        "Stopped translations will have to start again from the beginning. "
        "Finished books are not affected.",
        "ستبدأ الترجمات المتوقفة من البداية. لن تتأثر الكتب المكتملة.",
    ),
    "store.deleted": ("Temporary files deleted", "حُذفت الملفات المؤقتة"),
    "store.busy": (
        "Wait until all translations finish, or stop them first.",
        "انتظر حتى تنتهي كل الترجمات، أو أوقفها أولًا.",
    ),

    "group.about": ("About", "حول التطبيق"),
    "about.title": ("Kitab {version}", "كتاب {version}"),
    "about.desc": ("Free and open source (AGPL-3.0)", "مجاني ومفتوح المصدر (AGPL-3.0)"),
    "about.source": ("Source code", "الشيفرة المصدرية"),

    "common.cancel": ("Cancel", "إلغاء"),

    # ---- durations
    "time.s": ("{s}s", "{s} ث"),
    "time.ms": ("{m}m {s}s", "{m} د {s} ث"),
    "time.hm": ("{h}h {m}m", "{h} س {m} د"),
}

_PLURALS: dict[str, dict] = {
    "books.ready": {
        "en": ("1 book ready", "{n} books ready"),
        "ar": {
            "zero": "لا توجد كتب", "one": "كتاب واحد جاهز", "two": "كتابان جاهزان",
            "few": "{n} كتب جاهزة", "many": "{n} كتابًا جاهزًا", "other": "{n} كتاب جاهز",
        },
    },
    "books.started": {
        "en": ("1 book added to My translations", "{n} books added to My translations"),
        "ar": {
            "zero": "لم يُضف أي كتاب", "one": "أُضيف كتاب واحد إلى «ترجماتي»",
            "two": "أُضيف كتابان إلى «ترجماتي»", "few": "أُضيفت {n} كتب إلى «ترجماتي»",
            "many": "أُضيف {n} كتابًا إلى «ترجماتي»", "other": "أُضيف {n} كتاب إلى «ترجماتي»",
        },
    },
}
# fmt: on


def keys() -> set[str]:
    return set(_STRINGS)
