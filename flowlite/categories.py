"""App categorization (Wispr: EMAIL_APPS / MESSAGING_APPS / AI_APPS / DOCUMENT_APPS / Terminal).

Wispr matches the lowercased app name or URL with startsWith. FlowLite has the exe
name and window title (no browser URL), so for browsers it matches title keywords.
Style category follows Wispr's personalization mapping: email | work | personal | other.
"""

EMAIL = ["outlook", "olk", "thunderbird", "postbox", "emclient", "mailbird", "superhuman",
         "spark", "front", "hey", "proton mail", "mail"]
WORK_MESSAGING = ["slack", "ms-teams", "msteams", "teams", "zoom", "webex", "intercom",
                  "mattermost", "rocket.chat", "lark", "chime"]
MESSAGING = ["discord", "whatsapp", "telegram", "signal", "messenger", "beeper", "wechat",
             "weixin", "viber", "zalo", "line", "skype"] + WORK_MESSAGING
AI = ["chatgpt", "claude", "cursor", "windsurf", "code", "zed", "copilot", "gemini",
      "perplexity", "lm studio", "jan"]
DOCUMENT = ["notion", "winword", "excel", "powerpnt", "onenote", "notepad", "sublime_text",
            "idea64", "pycharm64", "obsidian", "figma", "acrord32", "acrobat", "wordpad"]
TERMINAL = ["windowsterminal", "cmd", "powershell", "pwsh", "warp", "alacritty", "hyper",
            "kitty", "wezterm-gui", "conhost", "mintty"]
BROWSERS = ["chrome", "msedge", "firefox", "brave", "opera", "vivaldi", "arc", "zen"]

# Browser tab title keyword -> category (stands in for Wispr's URL lists).
TITLE_KEYWORDS = [
    ("gmail", "email"), ("outlook", "email"), ("proton mail", "email"), ("yahoo mail", "email"),
    ("slack", "work"), ("microsoft teams", "work"), ("linkedin", "work"),
    ("whatsapp", "personal"), ("messenger", "personal"), ("telegram", "personal"),
    ("discord", "personal"), ("instagram", "personal"), (" / x", "personal"), ("reddit", "personal"),
    ("chatgpt", "ai"), ("claude", "ai"), ("gemini", "ai"), ("perplexity", "ai"),
    ("google docs", "document"), ("notion", "document"),
]


def _starts(name, entries):
    return any(name.startswith(e) for e in entries)


def classify(exe, title=""):
    """Return (app_type, style_category).

    app_type: ai | terminal | email | messaging | document | other  (prompt hint)
    style_category: email | work | personal | other                (which style to use)
    """
    name = exe.lower().removesuffix(".exe")
    t = title.lower()
    if _starts(name, BROWSERS):
        for keyword, kind in TITLE_KEYWORDS:
            if keyword in t:
                if kind in ("email", "work", "personal"):
                    return ("email" if kind == "email" else "messaging"), kind
                return kind, "other"
        return "other", "other"
    if _starts(name, AI):
        return "ai", "other"
    if _starts(name, TERMINAL):
        return "terminal", "other"
    if _starts(name, EMAIL):
        return "email", "email"
    if _starts(name, WORK_MESSAGING):
        return "messaging", "work"
    if _starts(name, MESSAGING):
        return "messaging", "personal"
    if _starts(name, DOCUMENT):
        return "document", "other"
    return "other", "other"
