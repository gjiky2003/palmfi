"""Templates module - all pages as Jinja2 strings"""

LANDING = r"""LANDING_PLACEHOLDER"""

LOGIN = r"""LOGIN_PLACEHOLDER"""

REGISTER = r"""REGISTER_PLACEHOLDER"""

DECISION = r"""DECISION_PLACEHOLDER"""

DASHBOARD = r"""DASHBOARD_PLACEHOLDER"""

TMPL = {
    "landing": LANDING,
    "login": LOGIN,
    "register": REGISTER,
    "decision": DECISION,
    "dashboard": DASHBOARD,
}

def render(name, **kwargs):
    from flask import render_template_string
    t = TMPL.get(name)
    if not t:
        return f"<h1>Template {name} not found</h1>"
    return render_template_string(t, **kwargs)
