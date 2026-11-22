# عقد التكامل الموحّد: scanner-fixer كخطوة أولى إلزامية لكل مسار OCR

> أولوية P1 من خارطة الطريق المتكاملة. هذا المستند هو **العقد الوحيد** الذي تستدعي
> به المنسّقات (IntelliFile plugins، EngineRouter في omni-medical-suite، خطوط أنابيب
> marathon) أداة scanner-fixer: ملف أو مجلد في الدخل، صور معيارية في الخرج، كائن
> حالة قابل للقراءة آليًا، وسياسة تجاوز صريحة.

## القاعدة الأساسية

كل مسار OCR **يجب** أن يستدعي scanner-fixer أولاً قبل أي خطوة تعرّف أو استخراج.
لا يُسمح بتخطي المعالجة إلا عبر `--bypass` الصريح، ويجب تسجيل قرار التجاوز في سجل
إجراءات المستدعي (action log) — انظر قسم سياسة التجاوز أدناه.

## الاستدعاء القياسي

### ملف واحد

```bash
scanner-fixer fix scan.jpg --output normalized.jpg --json
```

### مجلد كامل (دُفعة)

```bash
scanner-fixer batch ./scans/ --output-dir ./normalized/ --json
```

- يطبع stdout كائن JSON واحدًا فقط؛ لا يُكتب عليه أي نص آخر، لذا يمكن تحليله
  مباشرة بـ `json.loads`.
- الخرج الافتراضي بدون `--json` يبقى نصًا بشريًا مقروءًا (للاستخدام التفاعلي).
- خيارات المعالجة (`--no-crop`، `--binarize`، …) اختيارية وتبقى كما هي في الوضعين.

## مخطط مخرجات `--json`

| الحقل | النوع | الوصف |
|---|---|---|
| `input` | string | مسار الدخل كما مُرّر (ملف أو مجلد) |
| `outputs` | list[string] | مسارات الصور الناتجة الجاهزة للـ OCR (قائمة فارغة عند الفشل) |
| `operations_applied` | list[string] | العمليات المنفذة، مثل `crop`، `rotate`، `deskew`، `enhance`، `binarize`؛ فارغة عند `--bypass` |
| `processing_ms` | int | زمن المعالجة بالميلي ثانية |
| `status` | string | `ok` نجاح، `error` فشل، `bypassed` تجاوز صريح |
| `error` | string / null | رسالة الخطأ عند `error`، وإلا null |

أمثلة:

```json
{"input": "scan.jpg", "outputs": ["normalized.jpg"],
 "operations_applied": ["crop", "rotate", "deskew", "enhance"],
 "processing_ms": 812, "status": "ok", "error": null}
```

```json
{"input": "./scans/", "outputs": ["./normalized/a_fixed.png", "./normalized/b_fixed.png"],
 "operations_applied": ["crop", "deskew", "enhance"],
 "processing_ms": 1530, "status": "bypassed", "error": null}
```

## رموز الخروج (exit codes)

| الرمز | المعنى | متى |
|---|---|---|
| 0 | نجاح أو تجاوز صريح | `status` تساوي `ok` أو `bypassed` |
| 2 | فشل معالجة | تعذر قراءة أو معالجة ملف واحد أو أكثر (الدخل موجود لكنه تالف/غير مدعوم) |
| 3 | خطأ استخدام | مسار غير موجود، خيار غير معروف، وسيط ناقص |

الخروج برمز 1 يعني خطأً داخليًا غير متوقع خارج العقد (يُطبع تتبع كامل) ولا يجب
أن يتعامل معه المستدعي كفشل معالجة عادي.

## سياسة التجاوز (`--bypass`)

- كل مسار OCR **يجب** أن يستدعي scanner-fixer أولاً؛ التخطي الصامت ممنوع.
- يُسمح بالتخطي فقط عبر `--bypass` الصريح: عندها يُنسخ الدخل إلى الخرج دون أي
  تعديل، وترجع حالة `bypassed` برمز خروج 0، وتبقى `operations_applied` فارغة.
- نقطة الاستدعاء تبقى مطابقة تمامًا للمسار الطبيعي — نفس الأمر ونفس الخرج
  المتوقع؛ يتغير لدى المستدعي فقط إضافة `--bypass`. أي خيارات معالجة أخرى
  تُمرر معه تُتجاهل (لا معالجة إطلاقًا).
- **التسجيل إلزامي**: على المستدعي تسجيل قرار التجاوز وسببه في سجل الإجراءات
  الخاص به (action log). التجاوز اختيار واعٍ وموثق، وليس تخطيًا صامتًا.

## مثال: استدعاء scanner-fixer من منسّق (orchestrator)

```python
import json
import subprocess

def normalize_for_ocr(path: str, bypass: bool = False) -> dict:
    cmd = ["scanner-fixer", "fix", path, "--json"]
    if bypass:
        cmd.append("--bypass")  # قرار مسجل في action log المنسّق
    proc = subprocess.run(cmd, capture_output=True, text=True)
    status = json.loads(proc.stdout)  # كائن حالة واحد على stdout
    if proc.returncode != 0:  # 2 = فشل معالجة، 3 = خطأ استخدام
        raise RuntimeError(f"scanner-fixer exit {proc.returncode}: {status['error']}")
    if status["status"] == "bypassed":
        action_log.info(f"bypassed preprocessing for {path}")  # التسجيل إلزامي
    return status

ocr_input = normalize_for_ocr("scan.jpg")["outputs"][0]
```

## الخطوات التالية

- ربط إضافة `pii/ocr` في IntelliFile بهذا العقد: استدعاء عبر subprocess مع
  `--json` و`--bypass` وفق سياسة التسجيل أعلاه.
- توصيل `EngineRouter` في omni-medical-suite بنفس الاستدعاء الموحّد، واستبدال
  الاستيراد المباشر لـ `fix_scan` في `core/pipeline.py` باستدعاء CLI.
- تطبيق العقد نفسه على خطوط أنابيب marathon عند دمجها.
