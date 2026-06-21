"""
mac_control/accessibility.py — the Accessibility-tree engine.

This is the difference between "Jarvis can open an app" and "Jarvis can use
an app." It reads the macOS Accessibility (AX) tree — the same structured
data screen readers use — to SEE every button, field, link and label in the
frontmost app, then click or type into them BY NAME. No screenshots, no
vision model, no guessing pixel coordinates: structured, fast, and reliable.

Reading is safe and instant. Clicking and typing change things, so they ask
first via safety.confirm_action.

Everything is defensive: if pyobjc isn't installed or macOS hasn't been
granted Accessibility permission yet, you get a clear message telling you
exactly what to do — never a crash.
"""

import safety

# AX attribute / action constants are plain strings — using the literals
# avoids fragile constant imports across pyobjc versions.
_ROLE = "AXRole"
_TITLE = "AXTitle"
_DESC = "AXDescription"
_VALUE = "AXValue"
_CHILDREN = "AXChildren"
_WINDOWS = "AXWindows"
_FOCUSED_WINDOW = "AXFocusedWindow"
_PRESS = "AXPress"

# Roles worth surfacing as "things you can act on / read".
_INTERACTIVE = {"AXButton", "AXTextField", "AXTextArea", "AXMenuItem",
                "AXMenuButton", "AXLink", "AXCheckBox", "AXRadioButton",
                "AXPopUpButton", "AXComboBox", "AXSlider", "AXTab"}
_READABLE = _INTERACTIVE | {"AXStaticText", "AXHeading"}

MAX_NODES = 250
MAX_DEPTH = 20


class _Unavailable(Exception):
    pass


def _api():
    try:
        import ApplicationServices as AX
        from AppKit import NSWorkspace
    except ImportError:
        raise _Unavailable(
            "Accessibility control needs pyobjc — install it with "
            "`pip install -r requirements.txt`.")
    if not AX.AXIsProcessTrusted():
        raise _Unavailable(
            "Accessibility permission isn't granted yet. Open System Settings "
            "→ Privacy & Security → Accessibility and enable the app running "
            "Jarvis (your terminal or Python), then try again.")
    return AX, NSWorkspace


def _attr(AX, el, name):
    try:
        err, val = AX.AXUIElementCopyAttributeValue(el, name, None)
    except Exception:
        return None
    return val if err == 0 else None


def _frontmost(AX, NSWorkspace):
    app = NSWorkspace.sharedWorkspace().frontmostApplication()
    if app is None:
        raise _Unavailable("No frontmost application could be found.")
    el = AX.AXUIElementCreateApplication(app.processIdentifier())
    return el, app.localizedName()


def _root_window(AX, app_el):
    win = _attr(AX, app_el, _FOCUSED_WINDOW)
    if win is not None:
        return win
    wins = _attr(AX, app_el, _WINDOWS)
    return wins[0] if wins else app_el


def _walk(AX, el, depth, acc):
    if len(acc) >= MAX_NODES or depth > MAX_DEPTH:
        return
    role = _attr(AX, el, _ROLE)
    label = _attr(AX, el, _TITLE) or _attr(AX, el, _DESC)
    value = _attr(AX, el, _VALUE)
    if role in _READABLE and (label or (isinstance(value, str) and value.strip())):
        acc.append({"role": role, "label": (label or "").strip(),
                    "value": value if isinstance(value, str) else None,
                    "el": el})
    for child in (_attr(AX, el, _CHILDREN) or []):
        _walk(AX, child, depth + 1, acc)


def _scan() -> tuple[str, list[dict]]:
    AX, NSWorkspace = _api()
    app_el, app_name = _frontmost(AX, NSWorkspace)
    root = _root_window(AX, app_el)
    acc: list[dict] = []
    _walk(AX, root, 0, acc)
    return app_name, acc


def ax_read_screen(question: str = "") -> str:
    """Describe the interactive + text elements of the frontmost app's
    window, so Jarvis (or you) knows what can be clicked or read. Safe."""
    try:
        app_name, nodes = _scan()
    except _Unavailable as e:
        return str(e)
    if not nodes:
        return f"{app_name} is frontmost, but I can't read any elements from it."

    lines = [f"Frontmost app: {app_name}"]
    for i, n in enumerate(nodes, 1):
        bit = f"  [{i}] {n['role'].removeprefix('AX')}: {n['label'] or '—'}"
        if n["value"]:
            v = n["value"][:60].replace("\n", " ")
            bit += f"  = \"{v}\""
        lines.append(bit)
    return "\n".join(lines)


def _find(nodes: list[dict], query: str, roles: set[str] | None = None) -> dict | None:
    q = query.strip().lower()
    pool = [n for n in nodes if (roles is None or n["role"] in roles)]
    # exact label first, then substring.
    for n in pool:
        if n["label"].lower() == q:
            return n
    for n in pool:
        if q in n["label"].lower():
            return n
    return None


def ax_click(element: str) -> str:
    """Click a button/link/menu item in the frontmost app by its visible
    name. Gated, since clicking changes things."""
    try:
        app_name, nodes = _scan()
    except _Unavailable as e:
        return str(e)
    target = _find(nodes, element, _INTERACTIVE)
    if target is None:
        return (f"I couldn't find anything called '{element}' to click in "
                f"{app_name}. Ask me to read the screen to see what's there.")
    if not safety.confirm_action(
            f"Click '{target['label']}' ({target['role'].removeprefix('AX')}) "
            f"in {app_name}?", title="Click UI element"):
        return "Didn't click anything."
    AX, _ = _api()
    err = AX.AXUIElementPerformAction(target["el"], _PRESS)
    return (f"Clicked '{target['label']}'." if err == 0
            else f"Tried, but the click didn't take (AX error {err}).")


def ax_set_value(element: str, value: str) -> str:
    """Type text into a field in the frontmost app by its name/label. Gated."""
    try:
        app_name, nodes = _scan()
    except _Unavailable as e:
        return str(e)
    target = _find(nodes, element, {"AXTextField", "AXTextArea", "AXComboBox"})
    if target is None:
        return (f"I couldn't find a text field called '{element}' in "
                f"{app_name}.")
    if not safety.confirm_action(
            f"Type \"{value}\" into '{target['label'] or 'field'}' in "
            f"{app_name}?", title="Set field value"):
        return "Left the field as it was."
    AX, _ = _api()
    err = AX.AXUIElementSetAttributeValue(target["el"], _VALUE, value)
    return (f"Typed into '{target['label'] or 'the field'}'." if err == 0
            else f"Couldn't set that field (AX error {err}).")
