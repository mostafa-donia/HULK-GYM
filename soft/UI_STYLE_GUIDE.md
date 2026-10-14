# دليل تخصيص الألوان والأحجام

هذا الملف يشرح كيفية تغيير الألوان وحجم الخطوط والمساحات في واجهة التطبيق.

## أين يوجد الكود

- افتح `app.py`
- ابحث عن الدالة `apply_styles` في `MainWindow`
- عادة تكون في الجزء السفلي من الملف، حول السطر 3876

## ما الذي يمكن تغييره

### الألوان العامة
- `* { color: #E9EEF2; }` - لون النص العام
- `QWidget#central { background: #050B10; }` - لون الخلفية الرئيسية
- `QFrame#sidebar { background: #070D12; }` - لون خلفية الشريط الجانبي

### ألوان الأزرار
- `QPushButton#primaryButton` - أزرار الإجراءات الرئيسية
- `QPushButton#secondaryButton` - أزرار ثانوية
- `QPushButton#dangerButton` و `QPushButton#dangerButtonSmall` - أزرار الحذف
- `QPushButton#dashboardActionButton` - أزرار لوحة المدير

### العناوين والنصوص
- `QLabel#pageTitle, .pageTitle` - عناوين الصفحات الكبيرة
- `QLabel#pageSubtitle, .pageSubtitle` - نصوص وصف الصفحة
- `QLabel#sectionTitle, .sectionTitle` - عناوين أقسام داخل الصفحة
- `QLabel#fieldLabel, .fieldLabel` - تسميات الحقول

### الحقول والقوائم
- `QLineEdit#searchInput` - حقل البحث
- `QLineEdit, QComboBox, QDateEdit, QDoubleSpinBox` - الحقول العامة
- `QComboBox::drop-down` - زر القائمة المنسدلة

### البطاقات والمستطيلات
- `QFrame#detailCard` - بطاقة تفاصيل النموذج
- `QFrame#statCard` - بطاقة إحصائية
- `QFrame#dashboardHero` - لوحة المدير الرئيسية

### الجداول والتمرير
- `QTableWidget#memberDetailTable` - جدول تفاصيل الأعضاء
- `QTableWidget#darkTable` - جدول عام
- `QScrollBar` - أشرطة التمرير الرأسية والأفقية

## أمثلة سريعة

### تغيير لون خلفية الشريط الجانبي
```css
QFrame#sidebar {
    background: #1C2430;
}
```

### تكبير حجم عنوان الصفحة
```css
QLabel#pageTitle, .pageTitle {
    font-size: 36px;
}
```

### تغيير لون زر الحفظ الأساسي
```css
QPushButton#primaryButton {
    background: #FFB300;
    color: #071006;
}
```

### تغيير حجم الحقول
```css
QLineEdit, QComboBox, QDateEdit, QDoubleSpinBox {
    min-height: 34px;
    font-size: 16px;
}
```

## نصيحة للعثور على الكود بسرعة

ابحث في `app.py` عن الكلمات التالية:
- `apply_styles`
- `QPushButton#primaryButton`
- `QLabel#pageTitle`
- `QFrame#sidebar`
- `QLineEdit#searchInput`

## إذا أردت تغيير مسافات العناصر

ابحث عن `padding`, `margin`, `border-radius`, `min-height`, و `min-width` داخل قواعد الـ CSS في الدالة `apply_styles`.

## حفظ وتجربة التغييرات

- احفظ الملف بعد التعديل
- أعد تشغيل التطبيق لتظهر التعديلات الجديدة

---

إذا أردت، يمكنني بعد ذلك إنشاء ملف مشابه للمستخدم يحتوي فقط على الألوان الأساسية والخطوط، مع أمثلة جاهزة للتعديل.