from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
layout_path = ROOT / "android/hive-bench/overlay/activity_main.xml"
main_path = ROOT / "android/hive-bench/overlay/MainActivity.kt"

xml = layout_path.read_text()
kt = main_path.read_text()

# Give the app root a stable id so Android 16 system-bar insets can be applied.
if 'android:id="@+id/app_root"' not in xml:
    xml = xml.replace(
        '<LinearLayout xmlns:android="http://schemas.android.com/apk/res/android"\n    android:layout_width="match_parent"',
        '<LinearLayout xmlns:android="http://schemas.android.com/apk/res/android"\n    android:id="@+id/app_root"\n    android:layout_width="match_parent"',
        1,
    )

# Keep the primary action-card copy fully visible on the OnePlus Open.
xml = xml.replace(
    'android:id="@+id/home_chat_card" android:layout_width="0dp" android:layout_height="132dp"',
    'android:id="@+id/home_chat_card" android:layout_width="0dp" android:layout_height="150dp"',
    1,
)
xml = xml.replace(
    'android:id="@+id/home_work_card" android:layout_width="0dp" android:layout_height="132dp"',
    'android:id="@+id/home_work_card" android:layout_width="0dp" android:layout_height="150dp"',
    1,
)

# Avoid the narrow-card title splitting into "Diagnostic / s".
xml = xml.replace(
    'android:text="Diagnostics" android:textColor="#F4F9FC" android:textSize="17sp" android:textStyle="bold"',
    'android:text="Diagnostics" android:textColor="#F4F9FC" android:textSize="15sp" android:textStyle="bold" android:singleLine="true"',
    1,
)

# Tag the bottom bar for easier future inset-specific styling/debugging.
xml = xml.replace(
    '<LinearLayout android:layout_width="match_parent" android:layout_height="68dp" android:background="@drawable/hive_card"',
    '<LinearLayout android:id="@+id/bottom_nav" android:layout_width="match_parent" android:layout_height="68dp" android:background="@drawable/hive_card"',
    1,
)

# Android 15/16 enforce edge-to-edge for modern targets. Lift the app content and
# bottom navigation above the system navigation-bar inset instead of drawing behind it.
needle = '        setContentView(R.layout.activity_main)\n        window.statusBarColor = android.graphics.Color.parseColor("#050A11")\n'
replacement = '''        setContentView(R.layout.activity_main)\n\n        val appRoot = findViewById<View>(R.id.app_root)\n        appRoot.setOnApplyWindowInsetsListener { view, insets ->\n            view.setPadding(\n                view.paddingLeft,\n                view.paddingTop,\n                view.paddingRight,\n                insets.systemWindowInsetBottom,\n            )\n            insets\n        }\n        appRoot.requestApplyInsets()\n\n        window.statusBarColor = android.graphics.Color.parseColor("#050A11")\n'''
if replacement not in kt:
    if needle not in kt:
        raise SystemExit("Could not find MainActivity window setup anchor")
    kt = kt.replace(needle, replacement, 1)

layout_path.write_text(xml)
main_path.write_text(kt)

assert 'android:id="@+id/app_root"' in xml
assert 'android:id="@+id/bottom_nav"' in xml
assert 'home_chat_card" android:layout_width="0dp" android:layout_height="150dp"' in xml
assert 'home_work_card" android:layout_width="0dp" android:layout_height="150dp"' in xml
assert 'android:text="Diagnostics" android:textColor="#F4F9FC" android:textSize="15sp" android:textStyle="bold" android:singleLine="true"' in xml
assert 'insets.systemWindowInsetBottom' in kt
print("Hive Mobile Android 16 inset/layout fix applied")
