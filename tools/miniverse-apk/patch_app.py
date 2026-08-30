from pathlib import Path
import re
import shutil
import xml.etree.ElementTree as ET

root = Path('winlator-app')
java = root / 'app/src/main/java/com/winlator'
manifest = root / 'app/src/main/AndroidManifest.xml'
strings = root / 'app/src/main/res/values/strings.xml'

# Copy dedicated launcher source into Winlator.
shutil.copy2('tools/miniverse-apk/MiniverseActivity.java', java / 'MiniverseActivity.java')

# The standalone build only uses app-private files, so don't gate first-run
# rootfs installation behind obsolete external-storage permissions.
p = java / 'MainActivity.java'
t = p.read_text()
old = 'if (!requestAppPermissions()) RootFSInstaller.installIfNeeded(this);'
if old not in t:
    raise SystemExit('Expected MainActivity install line not found')
p.write_text(t.replace(old, 'RootFSInstaller.installIfNeeded(this);'))

# Make MiniverseActivity the launcher and keep MainActivity internal.
ET.register_namespace('android', 'http://schemas.android.com/apk/res/android')
A = '{http://schemas.android.com/apk/res/android}'
tree = ET.parse(manifest)
app = tree.getroot().find('application')
for activity in app.findall('activity'):
    if activity.get(A+'name') == 'com.winlator.MainActivity':
        for filt in list(activity.findall('intent-filter')):
            activity.remove(filt)
new = ET.Element('activity')
new.set(A+'name', 'com.winlator.MiniverseActivity')
new.set(A+'theme', '@style/AppThemeDark')
new.set(A+'exported', 'true')
new.set(A+'screenOrientation', 'sensorLandscape')
new.set(A+'configChanges', 'keyboard|keyboardHidden|orientation|screenSize|screenLayout|smallestScreenSize|density|navigation')
filt = ET.SubElement(new, 'intent-filter')
ET.SubElement(filt, 'action').set(A+'name', 'android.intent.action.MAIN')
ET.SubElement(filt, 'category').set(A+'name', 'android.intent.category.LAUNCHER')
app.insert(0, new)
tree.write(manifest, encoding='utf-8', xml_declaration=True)

# Exiting the compatibility screen should close this appliance rather than
# relaunching the launcher and immediately reopening the game. Locate the
# method by signature and balanced braces instead of depending on the order
# of neighboring methods in a specific Winlator revision.
p = java / 'XServerDisplayActivity.java'
t = p.read_text()
signature = '    private void exit() {'
start = t.find(signature)
if start < 0:
    raise SystemExit('Expected XServerDisplayActivity exit method not found')
brace_start = t.find('{', start)
depth = 0
end = None
for i in range(brace_start, len(t)):
    ch = t[i]
    if ch == '{':
        depth += 1
    elif ch == '}':
        depth -= 1
        if depth == 0:
            end = i + 1
            break
if end is None:
    raise SystemExit('Could not parse XServerDisplayActivity exit method')
if end < len(t) and t[end] == '\n':
    end += 1
replacement = '''    private void exit() {\n        winHandler.stop();\n        if (environment != null) environment.stopEnvironmentComponents();\n        ForegroundService.stopSession(this);\n        finishAndRemoveTask();\n    }\n'''
p.write_text(t[:start] + replacement + t[end:])

if strings.exists():
    t = strings.read_text()
    strings.write_text(re.sub(r'(<string name="app_name">).*?(</string>)', r'\1Miniverse Minigolf\2', t, count=1))

print('Android shell patched.')
