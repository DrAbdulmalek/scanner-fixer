"""
مُصلح الصور الممسوحة
إزالة الميلان + قص الحواف تلقائياً + تعديل يدوي + معالجة دفعية
Dr. Abdulmalek Al-Husseini
"""

import tkinter as tk
from tkinter import filedialog, messagebox, ttk
from PIL import Image, ImageTk
import cv2
import numpy as np
import os
import threading
import queue
from pathlib import Path


# ─────────────────────────────────────────
#  خوارزميات المعالجة  (v3 — محسّن)
# ─────────────────────────────────────────

# ثوابت جودة المعالجة المسبقة
_CANNY_LOW_RATIO  = 0.4   # نسبة العتبة الدنيا من العلوية
_MIN_TEXT_PIXELS  = 50    # أقل عدد بكسلات نصية لتفعيل minAreaRect
_MERGE_AGREE_TH  = 5.0   # عتبة الاتفاق بين الطريقتين (درجات)


def _normalize_rect_angle(angle: float, w: float, h: float) -> float:
    """تحويل زاوية minAreaRect (-90,0] إلى زاوية تصحيح صحيحة في (-45,45].

    OpenCV يُرجع الزاوية دائماً في النطاق [-90, 0) حيث:
      - المحور الأطول يكون أفقي دائماً
      - الزاوية السالبة = دوران عكس عقارب الساعة

    الإصلاح:
      1. إذا العرض < الطول (المستطيل عمودي) أضف 90°
      2. حول للنطاق (-90,90) ثم أضف/اطرح 180 لإبقائها في (-45,45]
    """
    if w < h:
        angle += 90.0
    # ضمان النطاق (-90, 90]
    angle = ((angle + 90) % 180) - 90
    return angle


def _detect_minarect(gray: np.ndarray) -> tuple:
    """طريقة 1: minAreaRect — ممتازة للنصوص الكثيفة.

    تُرجع (زاوية، ثقة 0-1). الثقة تعتمد على كثافة البكسلات النصية.
    """
    _, binary = cv2.threshold(gray, 0, 255,
                              cv2.THRESH_BINARY_INV + cv2.THRESH_OTSU)
    coords = np.column_stack(np.where(binary > 0))
    if len(coords) < _MIN_TEXT_PIXELS:
        return 0.0, 0.0

    rect = cv2.minAreaRect(coords)
    (_, _), (w, h), angle = rect
    corrected = _normalize_rect_angle(angle, w, h)

    # الثقة: نسبة البكسلات النصية من إجمالي الصورة
    text_ratio = len(coords) / gray.size
    confidence = min(1.0, text_ratio * 15)  # نسبة عالية = ثقة عالية
    return corrected, confidence


def _detect_hough(gray: np.ndarray) -> tuple:
    """طريقة 2: HoughLines — ممتازة للصفحات ذات الحواف الواضحة.

    تُرجع (زاوية، ثقة 0-1). الخطوط الأطول تُweighted أعلى.
    العتبات ديناميكية بناءً على تباين الصورة.
    """
    blurred = cv2.GaussianBlur(gray, (5, 5), 0)

    # عتبات Canny ديناميكية بناءً على تباين الصورة
    sigma = np.std(gray)
    high = max(80, int(min(200, sigma * 0.5)))
    low = max(30, int(high * _CANNY_LOW_RATIO))
    edges = cv2.Canny(blurred, low, high, apertureSize=3)

    lines = cv2.HoughLines(edges, 1, np.pi / 180, threshold=80)
    if lines is None:
        return 0.0, 0.0

    # جمع الزوايا مع أوزان (عدد البكسلات في كل خط = الطول التقريبي)
    weighted_angles = []
    for line in lines[:80]:
        rho, theta = line[0]
        a = np.degrees(theta) - 90
        if abs(a) < 45:
            # الوزن = 1 (كل خط متساوٍ في Hough standard، لكن نستخدم
            # قيمة rho المطلقة كوزن إضافي للخطوط الأقرب للأفقي)
            weight = 1.0 / (1.0 + abs(rho) * 0.001)
            weighted_angles.append((a, weight))

    if not weighted_angles:
        return 0.0, 0.0

    # weighted median عبر التراكمي
    angles_arr = np.array([a for a, _ in weighted_angles])
    weights_arr = np.array([w for _, w in weighted_angles])
    weights_arr /= weights_arr.sum()
    sorted_idx = np.argsort(angles_arr)
    cumsum = np.cumsum(weights_arr[sorted_idx])
    median_idx = sorted_idx[np.searchsorted(cumsum, 0.5)]
    angle_hough = float(angles_arr[median_idx])

    # الثقة: تعتمد على عدد الخطوط واتفاقها
    n_lines = len(weighted_angles)
    if n_lines >= 10:
        std = float(np.std(angles_arr))
        confidence = min(1.0, max(0.0, 1.0 - std / 5.0))
    else:
        confidence = min(0.6, n_lines / 10.0)
    return angle_hough, confidence


def detect_skew_angle(image: np.ndarray) -> tuple:
    """يكتشف زاوية الميلان بطريقتين ويختار الأدق.

    تُرجع (زاوية_التصحيح، ثقة_0_إلى_1، الطريقة_المختارة).
    """
    gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)

    angle_rect, conf_rect = _detect_minarect(gray)
    angle_hough, conf_hough = _detect_hough(gray)

    # لا يوجد كشف صالح من أي طريقة
    if conf_rect < 0.01 and conf_hough < 0.01:
        return 0.0, 0.0, "none"

    # إذا إحدى الطريقتين لم تكتشف شيئاً (ثقة ≈ 0)، نأخذ الأخرى
    if conf_rect < 0.01:
        return angle_hough, conf_hough, "hough"
    if conf_hough < 0.01:
        return angle_rect, conf_rect, "minarect"

    # الطريقتان أعطتا نتائج — هل تتفقان؟
    diff = abs(angle_rect - angle_hough)
    if diff < _MERGE_AGREE_TH:
        # متفقان: المتوسط المرجح بالثقة
        total_conf = conf_rect + conf_hough
        w_rect = conf_rect / total_conf
        w_hough = conf_hough / total_conf
        merged = angle_rect * w_rect + angle_hough * w_hough
        return merged, max(conf_rect, conf_hough), "merged"

    # متعارضتان: نأخذ الأعلى ثقة
    if conf_rect >= conf_hough:
        return angle_rect, conf_rect, "minarect"
    return angle_hough, conf_hough, "hough"


def deskew(image: np.ndarray, angle: float) -> np.ndarray:
    """يدور الصورة بالزاوية المعطاة مع خلفية بيضاء."""
    if abs(angle) < 0.05:
        return image
    (h, w) = image.shape[:2]
    M = cv2.getRotationMatrix2D((w / 2, h / 2), angle, 1.0)
    return cv2.warpAffine(image, M, (w, h),
                          flags=cv2.INTER_CUBIC,
                          borderMode=cv2.BORDER_CONSTANT,
                          borderValue=(255, 255, 255))


def auto_crop(image: np.ndarray, margin: int = 12) -> np.ndarray:
    """يقص الحواف الفارغة ذكياً. يعمل مع أي خلفية فاتحة."""
    gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
    bg_val = np.percentile(gray, 95)
    threshold = max(220, bg_val - 15)
    mask = gray < threshold
    if not np.any(mask):
        return image
    rows = np.any(mask, axis=1)
    cols = np.any(mask, axis=0)
    y0, y1 = np.where(rows)[0][[0, -1]]
    x0, x1 = np.where(cols)[0][[0, -1]]
    y0 = max(0, y0 - margin)
    y1 = min(image.shape[0] - 1, y1 + margin)
    x0 = max(0, x0 - margin)
    x1 = min(image.shape[1] - 1, x1 + margin)
    return image[y0:y1 + 1, x0:x1 + 1]


def process_single(image: np.ndarray, extra_angle: float = 0.0,
                   do_crop: bool = True,
                   cached_auto: float = None,
                   ignore_auto: bool = False) -> tuple:
    """المعالجة الكاملة لصورة واحدة.

    المعاملات:
        extra_angle: تصحيح يدوي إضافي
        do_crop: هل نقص الحواف؟
        cached_auto: زاوية تلقائية مخزنة (لتجنب إعادة الحساب في السلايدر)
        ignore_auto: تجاهل الكشف التلقائي واستخدم اليدوي فقط

    تُرجع (الصورة_النتيجة، الزاوية_التلقائية، الزاوية_الإجمالية، الثقة، طريقة_الكشف)
    """
    if ignore_auto:
        auto_angle = 0.0
        confidence = 0.0
        method = "manual-only"
    elif cached_auto is not None:
        auto_angle = cached_auto
        confidence = 1.0
        method = "cached"
    else:
        auto_angle, confidence, method = detect_skew_angle(image)

    total_angle = auto_angle + extra_angle
    rotated = deskew(image, total_angle)
    result = auto_crop(rotated) if do_crop else rotated
    return result, auto_angle, total_angle, confidence, method


# ─────────────────────────────────────────
#  الألوان
# ─────────────────────────────────────────

DARK_BG    = "#1e1e2e"
PANEL_BG   = "#2a2a3e"
ACCENT     = "#7c6af7"
ACCENT2    = "#56b6c2"
TEXT_LIGHT = "#cdd6f4"
TEXT_DIM   = "#6e6a8a"
DANGER     = "#f38ba8"
BORDER     = "#3d3d5c"
SLIDER_BG  = "#313148"


# ─────────────────────────────────────────
#  التطبيق
# ─────────────────────────────────────────

class ScannerFixerApp:
    def __init__(self, root: tk.Tk):
        self.root = root
        self.root.title("مُصلح الصور الممسوحة")
        self.root.geometry("1350x900")
        self.root.minsize(950, 650)
        self.root.configure(bg=DARK_BG)

        self.cv_original      = None
        self.cv_processed     = None
        self.current_file     = ""
        self.batch_folder     = ""
        self.msg_queue        = queue.Queue()
        self.is_batch_running = False
        self.cancel_batch     = False

        # متغيرات التحكم اليدوي
        self.manual_angle     = tk.DoubleVar(value=0.0)
        self.do_crop          = tk.BooleanVar(value=True)
        self.ignore_auto       = tk.BooleanVar(value=False)
        self._slider_job      = None          # debounce timer
        self._cached_auto_angle = None       # cache for slider performance

        self._build_ui()
        self._bind_shortcuts()
        self._poll_queue()

    # ══════════════════════════════════════
    #  اختصارات لوحة المفاتيح
    # ══════════════════════════════════════

    def _bind_shortcuts(self):
        """اختصارات لوحة المفاتيح لتسريع العمل"""
        self.root.bind('<Control-o>', lambda e: self._open_image())
        self.root.bind('<Control-s>', lambda e: self._save_image())
        self.root.bind('<Control-m>', lambda e: self._open_folder())
        self.root.bind('<space>', lambda e: self._run_process())

    # ══════════════════════════════════════
    #  بناء الواجهة
    # ══════════════════════════════════════

    def _build_ui(self):
        self._build_toolbar()
        self._build_middle()   # صور + لوحة تحكم جانبية
        self._build_log()
        self._build_statusbar()

    # ── شريط الأدوات ──────────────────────
    def _build_toolbar(self):
        bar = tk.Frame(self.root, bg=PANEL_BG, pady=8)
        bar.pack(fill=tk.X)

        tk.Label(bar, text="مُصلح الصور الممسوحة",
                 bg=PANEL_BG, fg=ACCENT,
                 font=("Arial", 14, "bold")).pack(side=tk.RIGHT, padx=18)

        buttons = [
            ("📂 فتح صورة",    ACCENT,    self._open_image,  "btn_open"),
            ("📁 معالجة مجلد", "#5a5a8a", self._open_folder, "btn_folder"),
            ("⚙ معالجة",       "#27ae60", self._run_process, "btn_process"),
            ("💾 حفظ",          "#2980b9", self._save_image,  "btn_save"),
            ("⛔ إيقاف",        DANGER,    self._stop_batch,  "btn_stop"),
        ]
        self.btns = {}
        for text, color, cmd, key in buttons:
            b = tk.Button(bar, text=text, command=cmd,
                          bg=color, fg="white",
                          font=("Arial", 10, "bold"),
                          relief=tk.FLAT, padx=12, pady=5,
                          cursor="hand2", activebackground=BORDER)
            b.pack(side=tk.LEFT, padx=4)
            self.btns[key] = b

        self.btns["btn_process"].config(state=tk.DISABLED)
        self.btns["btn_save"].config(state=tk.DISABLED)
        self.btns["btn_stop"].config(state=tk.DISABLED)

        self.progress_var = tk.DoubleVar()
        self.progress_lbl = tk.Label(bar, text="", bg=PANEL_BG,
                                     fg=TEXT_DIM, font=("Arial", 9))
        self.progress_lbl.pack(side=tk.LEFT, padx=(16, 4))
        self.progressbar = ttk.Progressbar(bar, variable=self.progress_var,
                                           length=200, maximum=100)
        self.progressbar.pack(side=tk.LEFT, padx=4)

    # ── المنطقة الوسطى ────────────────────
    def _build_middle(self):
        mid = tk.Frame(self.root, bg=DARK_BG)
        mid.pack(fill=tk.BOTH, expand=True, padx=12, pady=(8, 0))

        # لوحتا الصور (تأخذان المساحة المتبقية)
        img_area = tk.Frame(mid, bg=DARK_BG)
        img_area.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)

        self.lbl_orig = self._image_panel(img_area, "الصورة الأصلية", 0)
        self.lbl_proc = self._image_panel(img_area, "بعد المعالجة",   1)
        img_area.columnconfigure(0, weight=1)
        img_area.columnconfigure(1, weight=1)
        img_area.rowconfigure(0, weight=1)

        # لوحة التحكم اليدوي (يمين ثابت)
        self._build_control_panel(mid)

    def _image_panel(self, parent, title, col):
        frame = tk.Frame(parent, bg=PANEL_BG,
                         highlightbackground=BORDER, highlightthickness=1)
        frame.grid(row=0, column=col,
                   padx=(0, 6) if col == 0 else (0, 0),
                   sticky="nsew")
        tk.Label(frame, text=title, bg=PANEL_BG, fg=ACCENT2,
                 font=("Arial", 10, "bold")).pack(pady=(8, 3))
        lbl = tk.Label(frame, bg=DARK_BG,
                       text="—\nاختر صورة", fg=TEXT_DIM,
                       font=("Arial", 12))
        lbl.pack(fill=tk.BOTH, expand=True, padx=6, pady=(0, 6))
        return lbl

    # ── لوحة التحكم اليدوي ────────────────
    def _build_control_panel(self, parent):
        panel = tk.Frame(parent, bg=SLIDER_BG,
                         highlightbackground=BORDER, highlightthickness=1,
                         width=230)
        panel.pack(side=tk.RIGHT, fill=tk.Y, padx=(8, 0))
        panel.pack_propagate(False)

        def section(text):
            tk.Label(panel, text=text, bg=SLIDER_BG, fg=ACCENT2,
                     font=("Arial", 10, "bold")).pack(
                         anchor="w", padx=14, pady=(14, 2))
            tk.Frame(panel, bg=BORDER, height=1).pack(fill=tk.X, padx=14)

        # ── تصحيح يدوي ──
        section("✏ تصحيح يدوي للزاوية")

        tk.Label(panel, text="أضف زاوية إضافية فوق الكشف التلقائي:",
                 bg=SLIDER_BG, fg=TEXT_DIM,
                 font=("Arial", 8), wraplength=200,
                 justify="right").pack(anchor="w", padx=14, pady=(6, 2))

        # قراءة الزاوية الحالية
        self.angle_display = tk.Label(panel, text="0.0°",
                                      bg=SLIDER_BG, fg=ACCENT,
                                      font=("Arial", 22, "bold"))
        self.angle_display.pack(pady=(4, 0))

        self.slider = tk.Scale(
            panel,
            from_=-30, to=30,
            resolution=0.5,
            orient=tk.HORIZONTAL,
            variable=self.manual_angle,
            command=self._on_slider,
            bg=SLIDER_BG, fg=TEXT_LIGHT,
            troughcolor=BORDER,
            highlightthickness=0,
            showvalue=False,
            length=200,
        )
        self.slider.pack(padx=14, pady=2)

        # أزرار ضبط دقيق
        fine = tk.Frame(panel, bg=SLIDER_BG)
        fine.pack(pady=4)
        for delta, lbl in [(-1, "◀ -1°"), (-0.5, "◀ -0.5°"),
                            (+0.5, "+0.5° ▶"), (+1, "+1° ▶")]:
            tk.Button(fine, text=lbl,
                      command=lambda d=delta: self._nudge(d),
                      bg=BORDER, fg=TEXT_LIGHT,
                      font=("Arial", 8), relief=tk.FLAT,
                      padx=5, pady=3, cursor="hand2").pack(
                          side=tk.LEFT, padx=2)

        # إعادة الضبط
        tk.Button(panel, text="↺ إعادة الضبط (0°)",
                  command=self._reset_angle,
                  bg=ACCENT, fg="white",
                  font=("Arial", 9, "bold"),
                  relief=tk.FLAT, pady=5, cursor="hand2").pack(
                      fill=tk.X, padx=14, pady=(6, 2))

        # معلومات الزاوية التلقائية
        self.auto_angle_lbl = tk.Label(
            panel, text="الزاوية التلقائية: —",
            bg=SLIDER_BG, fg=TEXT_DIM,
            font=("Arial", 8))
        self.auto_angle_lbl.pack(anchor="w", padx=14, pady=(2, 0))

        self.total_angle_lbl = tk.Label(
            panel, text="الزاوية الإجمالية: —",
            bg=SLIDER_BG, fg=ACCENT2,
            font=("Arial", 9, "bold"))
        self.total_angle_lbl.pack(anchor="w", padx=14, pady=(0, 4))

        # ── خيارات ──
        section("⚙ خيارات")

        tk.Checkbutton(
            panel, text="قص الحواف تلقائياً",
            variable=self.do_crop,
            bg=SLIDER_BG, fg=TEXT_LIGHT,
            selectcolor=BORDER,
            activebackground=SLIDER_BG,
            font=("Arial", 9),
            command=self._on_option_change,
        ).pack(anchor="w", padx=14, pady=(10, 4))

        tk.Checkbutton(
            panel, text="تجاهل الكشف التلقائي",
            variable=self.ignore_auto,
            bg=SLIDER_BG, fg=TEXT_LIGHT,
            selectcolor=BORDER,
            activebackground=SLIDER_BG,
            font=("Arial", 9),
            command=self._on_option_change,
        ).pack(anchor="w", padx=14, pady=(4, 4))

        # ── تلميح ──
        section("💡 تلميح")
        tk.Label(panel,
                 text="حرّك السلايدر لتصحيح\n"
                      "ما لم يكتشفه التلقائي.\n\n"
                      "الصورة تتحدث فورياً\n"
                      "بعد ثانية من التوقف.",
                 bg=SLIDER_BG, fg=TEXT_DIM,
                 font=("Arial", 8), justify="right",
                 wraplength=200).pack(anchor="w", padx=14, pady=8)

    # ── سجل العمليات ──────────────────────
    def _build_log(self):
        frame = tk.Frame(self.root, bg=PANEL_BG,
                         highlightbackground=BORDER, highlightthickness=1)
        frame.pack(fill=tk.X, padx=12, pady=(8, 0))

        tk.Label(frame, text="سجل العمليات",
                 bg=PANEL_BG, fg=ACCENT2,
                 font=("Arial", 10, "bold")).pack(
                     anchor="w", padx=10, pady=(6, 2))

        cols = ("file", "auto_angle", "manual_adj",
                "total_angle", "size_before", "size_after", "status")
        self.log_tree = ttk.Treeview(frame, columns=cols,
                                     show="headings", height=4)
        hdrs = {
            "file":        "الملف",
            "auto_angle":  "زاوية تلقائية",
            "manual_adj":  "تعديل يدوي",
            "total_angle": "الإجمالي",
            "size_before": "قبل",
            "size_after":  "بعد",
            "status":      "الحالة",
        }
        widths = {
            "file": 310, "auto_angle": 110, "manual_adj": 90,
            "total_angle": 90, "size_before": 110,
            "size_after": 110, "status": 80,
        }
        for c, h in hdrs.items():
            self.log_tree.heading(c, text=h)
            self.log_tree.column(c, width=widths[c], anchor="center")

        style = ttk.Style()
        style.theme_use("clam")
        style.configure("Treeview",
                        background=PANEL_BG, foreground=TEXT_LIGHT,
                        fieldbackground=PANEL_BG, rowheight=22)
        style.configure("Treeview.Heading",
                        background=BORDER, foreground=TEXT_LIGHT)
        style.map("Treeview", background=[("selected", ACCENT)])

        sb = ttk.Scrollbar(frame, orient=tk.VERTICAL,
                           command=self.log_tree.yview)
        self.log_tree.configure(yscrollcommand=sb.set)
        self.log_tree.pack(side=tk.LEFT, fill=tk.X,
                           expand=True, padx=(10, 0), pady=6)
        sb.pack(side=tk.LEFT, fill=tk.Y, pady=6)

    def _build_statusbar(self):
        bar = tk.Frame(self.root, bg=BORDER, height=26)
        bar.pack(fill=tk.X, side=tk.BOTTOM)
        self.status_var = tk.StringVar(value="جاهز")
        tk.Label(bar, textvariable=self.status_var,
                 bg=BORDER, fg=TEXT_LIGHT,
                 font=("Arial", 9), anchor="w").pack(
                     side=tk.LEFT, padx=10)
        self.angle_status = tk.StringVar()
        tk.Label(bar, textvariable=self.angle_status,
                 bg=BORDER, fg=ACCENT2,
                 font=("Arial", 9, "bold")).pack(
                     side=tk.RIGHT, padx=10)

    # ══════════════════════════════════════
    #  عرض الصور
    # ══════════════════════════════════════

    def _show_cv(self, cv_img, label, max_w=560, max_h=470):
        rgb = cv2.cvtColor(cv_img, cv2.COLOR_BGR2RGB)
        pil = Image.fromarray(rgb)
        pil.thumbnail((max_w, max_h), Image.Resampling.LANCZOS)
        tk_img = ImageTk.PhotoImage(pil)
        label.configure(image=tk_img, text="")
        label.image = tk_img

    # ══════════════════════════════════════
    #  منطق السلايدر
    # ══════════════════════════════════════

    def _on_slider(self, val=None):
        v = self.manual_angle.get()
        self.angle_display.config(text=f"{v:+.1f}°")
        # debounce: انتظر 400ms بعد آخر حركة ثم طبّق
        if self._slider_job:
            self.root.after_cancel(self._slider_job)
        self._slider_job = self.root.after(400, self._apply_manual)

    def _nudge(self, delta):
        cur = self.manual_angle.get()
        new = max(-30, min(30, cur + delta))
        self.manual_angle.set(new)
        self._on_slider()

    def _reset_angle(self):
        self.manual_angle.set(0.0)
        self.angle_display.config(text="0.0°")
        self._apply_manual()

    def _on_option_change(self):
        if self.cv_original is not None:
            self._apply_manual()

    def _apply_manual(self):
        """يُطبّق التدوير الكلي (تلقائي + يدوي) ويعرض النتيجة فوراً.

        يُخزّن الزاوية التلقائية عند أول كشف لتجنب إعادة الحساب
        عند كل تحريك للسلايدر (تحسين الأداء).
        """
        if self.cv_original is None:
            return
        extra = self.manual_angle.get()
        do_crop = self.do_crop.get()
        ignore_auto = self.ignore_auto.get()

        # استخدم الزاوية المخزنة إن وُجدت (لتفادي إعادة الكشف)
        cached = getattr(self, '_cached_auto_angle', None)
        result, auto_a, total_a, conf, method = process_single(
            self.cv_original.copy(), extra, do_crop,
            cached_auto=cached, ignore_auto=ignore_auto,
        )
        # خزّن الزاوية التلقائية عند أول كشف
        if cached is None:
            self._cached_auto_angle = auto_a

        self.cv_processed = result
        self._show_cv(result, self.lbl_proc)
        self.btns["btn_save"].config(state=tk.NORMAL)

        # مؤشر الثقة بلون
        conf_pct = int(conf * 100)
        conf_icon = "🟢" if conf_pct >= 70 else ("🟡" if conf_pct >= 40 else "🔴")
        self.auto_angle_lbl.config(
            text=f"تلقائي: {auto_a:+.2f}° {conf_icon}{conf_pct}% [{method}]")
        self.total_angle_lbl.config(
            text=f"الإجمالي: {total_a:+.2f}°")
        self.angle_status.set(
            f"تلقائي: {auto_a:+.2f}° | يدوي: {extra:+.1f}° | "
            f"إجمالي: {total_a:+.2f}°")

    # ══════════════════════════════════════
    #  أوامر الأزرار
    # ══════════════════════════════════════

    def _open_image(self):
        path = filedialog.askopenfilename(
            title="اختر صورة",
            filetypes=[("صور", "*.png *.jpg *.jpeg *.bmp *.tiff *.tif"),
                       ("الكل", "*.*")])
        if not path:
            return
        img = cv2.imread(path)
        if img is None:
            messagebox.showerror("خطأ", "تعذر قراءة الصورة")
            return
        self.cv_original  = img
        self.cv_processed = None
        self.current_file = path
        self.batch_folder = ""
        self.manual_angle.set(0.0)
        self.angle_display.config(text="0.0°")
        self._cached_auto_angle = None
        self._show_cv(img, self.lbl_orig)
        self.lbl_proc.configure(image="", text="—\nبعد المعالجة", fg=TEXT_DIM)
        self.btns["btn_process"].config(state=tk.NORMAL)
        self.btns["btn_save"].config(state=tk.DISABLED)
        self.auto_angle_lbl.config(text="الزاوية التلقائية: —")
        self.total_angle_lbl.config(text="الزاوية الإجمالية: —")
        self.angle_status.set("")
        self._set_status(f"تم تحميل: {os.path.basename(path)}")

    def _open_folder(self):
        folder = filedialog.askdirectory(title="اختر مجلد الصور")
        if not folder:
            return
        files = [f for f in os.listdir(folder)
                 if f.lower().endswith(
                     (".png", ".jpg", ".jpeg", ".bmp", ".tiff", ".tif"))]
        if not files:
            messagebox.showwarning("تنبيه", "لا توجد صور في المجلد المختار")
            return
        self.batch_folder = folder
        self.cv_original  = None
        self.btns["btn_process"].config(state=tk.NORMAL)
        self.btns["btn_save"].config(state=tk.DISABLED)
        self._set_status(f"مجلد: {folder}  ({len(files)} صورة)")

    def _run_process(self):
        if self.batch_folder:
            self._start_batch()
        elif self.cv_original is not None:
            self._process_single_ui()

    def _process_single_ui(self):
        self._set_status("جاري المعالجة…")
        self._cached_auto_angle = None  # إعادة الكشف لكل صورة جديدة
        extra = self.manual_angle.get()
        do_crop = self.do_crop.get()
        ignore_auto = self.ignore_auto.get()
        result, auto_a, total_a, conf, method = process_single(
            self.cv_original.copy(), extra, do_crop, ignore_auto=ignore_auto)
        self._cached_auto_angle = auto_a
        self.cv_processed = result
        self._show_cv(result, self.lbl_proc)
        self.btns["btn_save"].config(state=tk.NORMAL)
        h0, w0 = self.cv_original.shape[:2]
        h1, w1 = result.shape[:2]
        conf_pct = int(conf * 100)
        status_icon = "🟢" if conf_pct >= 70 else ("🟡" if conf_pct >= 40 else "🔴")
        self._log_row(os.path.basename(self.current_file),
                      auto_a, extra, total_a,
                      f"{w0}×{h0}", f"{w1}×{h1}",
                      f"✓ {conf_icon}{conf_pct}%")
        self.auto_angle_lbl.config(
            text=f"تلقائي: {auto_a:+.2f}° {conf_icon}{conf_pct}% [{method}]")
        self.total_angle_lbl.config(
            text=f"الإجمالي: {total_a:+.2f}°")
        self.angle_status.set(
            f"تلقائي: {auto_a:+.2f}° | يدوي: {extra:+.1f}° | "
            f"إجمالي: {total_a:+.2f}°")
        self._set_status("تمت المعالجة بنجاح")

    # ── معالجة دفعية ──────────────────────
    def _start_batch(self):
        if self.is_batch_running:
            return
        extra = self.manual_angle.get()
        self.cancel_batch     = False
        self.is_batch_running = True
        self.btns["btn_stop"].config(state=tk.NORMAL)
        self.btns["btn_process"].config(state=tk.DISABLED)
        threading.Thread(
            target=self._batch_worker,
            args=(self.batch_folder, extra, self.do_crop.get(),
                  self.ignore_auto.get()),
            daemon=True,
        ).start()

    def _batch_worker(self, folder, extra_angle, do_crop, ignore_auto=False):
        files = sorted([
            f for f in os.listdir(folder)
            if f.lower().endswith(
                (".png", ".jpg", ".jpeg", ".bmp", ".tiff", ".tif"))
        ])
        total   = len(files)
        out_dir = os.path.join(folder, "Processed")
        os.makedirs(out_dir, exist_ok=True)
        done = 0
        for fname in files:
            if self.cancel_batch:
                break
            fpath = os.path.join(folder, fname)
            img   = cv2.imread(fpath)
            if img is None:
                self.msg_queue.put(
                    ("log", fname, None, extra_angle, None,
                     "—", "—", "✗ خطأ"))
                continue
            try:
                result, auto_a, total_a, conf, method = process_single(
                    img, extra_angle, do_crop, ignore_auto=ignore_auto)
                out_path = os.path.join(out_dir, fname)
                cv2.imwrite(out_path, result)
                h0, w0 = img.shape[:2]
                h1, w1 = result.shape[:2]
                conf_pct = int(conf * 100)
                self.msg_queue.put(
                    ("log", fname, auto_a, extra_angle, total_a,
                     f"{w0}×{h0}", f"{w1}×{h1}",
                     f"✓ {conf_pct}%"))
                self.msg_queue.put(("show_proc", result.copy()))
            except Exception as e:
                self.msg_queue.put(
                    ("log", fname, None, extra_angle, None,
                     "—", "—", f"✗ {e}"))
            done += 1
            self.msg_queue.put(("progress", done, total))

        self.msg_queue.put(("done", done, total, out_dir))

    def _stop_batch(self):
        self.cancel_batch = True
        self._set_status("جاري الإيقاف…")

    def _save_image(self):
        if self.cv_processed is None:
            return
        default = ""
        if self.current_file:
            p       = Path(self.current_file)
            default = str(p.parent / (p.stem + "_fixed" + p.suffix))
        path = filedialog.asksaveasfilename(
            initialfile=default,
            defaultextension=".png",
            filetypes=[("PNG", "*.png"), ("JPEG", "*.jpg"),
                       ("الكل", "*.*")])
        if path:
            cv2.imwrite(path, self.cv_processed)
            self._set_status(f"تم الحفظ: {os.path.basename(path)}")

    # ══════════════════════════════════════
    #  مساعدات
    # ══════════════════════════════════════

    def _set_status(self, msg):
        self.status_var.set(msg)

    def _log_row(self, fname, auto_a, manual_a, total_a, sb, sa, status):
        def fmt(v):
            return f"{v:+.2f}°" if v is not None else "—"
        self.log_tree.insert("", 0, values=(
            fname, fmt(auto_a), fmt(manual_a), fmt(total_a), sb, sa, status))
        kids = self.log_tree.get_children()
        if len(kids) > 200:
            self.log_tree.delete(kids[-1])

    def _poll_queue(self):
        try:
            while True:
                msg  = self.msg_queue.get_nowait()
                kind = msg[0]
                if kind == "progress":
                    _, done, total = msg
                    self.progress_var.set(done / total * 100)
                    self.progress_lbl.config(text=f"{done}/{total}")
                    self._set_status(f"معالجة {done}/{total}…")
                elif kind == "log":
                    _, fname, auto_a, manual_a, total_a, sb, sa, st = msg
                    self._log_row(fname, auto_a, manual_a, total_a, sb, sa, st)
                elif kind == "show_proc":
                    _, img = msg
                    self._show_cv(img, self.lbl_proc)
                elif kind == "done":
                    _, done, total, out_dir = msg
                    self.is_batch_running = False
                    self.btns["btn_stop"].config(state=tk.DISABLED)
                    self.btns["btn_process"].config(state=tk.NORMAL)
                    self.progress_var.set(100)
                    self._set_status(
                        f"اكتمل: {done}/{total} — المخرجات: {out_dir}")
                    messagebox.showinfo(
                        "اكتملت المعالجة",
                        f"تمت معالجة {done} صورة من أصل {total}\n\n"
                        f"المجلد الناتج:\n{out_dir}")
        except queue.Empty:
            pass
        finally:
            self.root.after(80, self._poll_queue)


# ─────────────────────────────────────────
if __name__ == "__main__":
    root = tk.Tk()
    ScannerFixerApp(root)
    root.mainloop()
