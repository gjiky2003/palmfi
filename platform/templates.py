# Templates module for AI Lending Company

LANDING = """<!DOCTYPE html>
<html lang="en">
<head><meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1.0">
<title>PalmFi — AI Powered Personal Loans</title>
<script src="https://cdn.tailwindcss.com"></script>
<script>tailwind.config={theme:{extend:{colors:{primary:"#1a365d",accent:"#059669"}}}}</script>
<link rel="stylesheet" href="https://cdnjs.cloudflare.com/ajax/libs/font-awesome/6.5.0/css/all.min.css">
</head>
<body class="bg-gray-50 min-h-screen">
<nav class="bg-primary text-white shadow-lg">
<div class="max-w-7xl mx-auto px-4">
<div class="flex justify-between h-16 items-center">
<a href="/" class="text-2xl font-bold"><i class="fas fa-bolt mr-2 text-accent"></i>PalmFi</a>
<div class="flex items-center space-x-4">
<a href="/login" class="bg-accent hover:bg-green-700 px-4 py-2 rounded-lg text-sm">Sign In</a>
<a href="/register" class="border border-white hover:bg-white hover:text-primary px-4 py-2 rounded-lg text-sm">Get Started</a>
</div></div></div></nav>

<div class="bg-gradient-to-br from-primary via-blue-800 to-blue-900 text-white">
<div class="max-w-7xl mx-auto px-4 py-24">
<div class="grid md:grid-cols-2 gap-12 items-center">
<div>
<h1 class="text-5xl font-bold leading-tight">AI-Powered Loans.<br><span class="text-accent">Minutes, Not Days.</span></h1>
<p class="text-xl mt-6 text-blue-200">Get funded instantly with our AI underwriting. No humans, no waiting.</p>
<div class="mt-8 space-x-4">
<a href="/apply" class="bg-accent hover:bg-green-700 text-white px-8 py-4 rounded-xl text-lg font-semibold inline-block shadow-lg">Check Your Rate</a>
<a href="/register" class="border-2 border-white hover:bg-white hover:text-primary px-8 py-4 rounded-xl text-lg font-semibold inline-block">Create Account</a>
</div>
<div class="mt-8 flex space-x-6 text-sm text-blue-300">
<span><i class="fas fa-check-circle text-accent mr-1"></i>5.99%-35.99% APR</span>
<span><i class="fas fa-check-circle text-accent mr-1"></i>$500-$50,000</span>
<span><i class="fas fa-check-circle text-accent mr-1"></i>Instant Decision</span>
</div></div>
<div class="hidden md:block bg-white/10 backdrop-blur rounded-2xl p-8">
<div class="text-center mb-4"><span class="bg-accent/20 text-accent px-4 py-1 rounded-full text-sm font-semibold">LIVE DEMO</span></div>
<div class="space-y-3">
<div class="flex justify-between"><span>Risk Score</span><span class="font-bold text-accent">9/100</span></div>
<div class="w-full bg-white/20 rounded-full h-2"><div class="bg-accent h-2 rounded-full" style="width:9%"></div></div>
<div class="flex justify-between text-lg"><span>APR Offer</span><span class="font-bold text-accent">7.11%</span></div>
<div class="flex justify-between"><span>Loan Amount</span><span class="font-bold">$25,000</span></div>
<div class="border-t border-white/20 pt-3 mt-3 text-center text-accent font-bold"><i class="fas fa-robot mr-2"></i>AI DECISION: APPROVED</div>
</div></div></div></div></div>

<div class="max-w-7xl mx-auto px-4 py-20">
<h2 class="text-3xl font-bold text-center mb-12">Why PalmFi?</h2>
<div class="grid md:grid-cols-3 gap-8">
<div class="bg-white rounded-2xl shadow-lg p-8"><div class="bg-accent/10 w-16 h-16 rounded-xl flex items-center justify-center mb-4"><i class="fas fa-brain text-3xl text-accent"></i></div><h3 class="text-xl font-semibold mb-2">AI Underwriting</h3><p class="text-gray-600">Our ensemble AI analyzes 18+ risk factors in milliseconds.</p></div>
<div class="bg-white rounded-2xl shadow-lg p-8"><div class="bg-blue-100 w-16 h-16 rounded-xl flex items-center justify-center mb-4"><i class="fas fa-bolt text-3xl text-blue-600"></i></div><h3 class="text-xl font-semibold mb-2">Instant Funding</h3><p class="text-gray-600">From application to funds in under 5 minutes.</p></div>
<div class="bg-white rounded-2xl shadow-lg p-8"><div class="bg-purple-100 w-16 h-16 rounded-xl flex items-center justify-center mb-4"><i class="fas fa-shield text-3xl text-purple-600"></i></div><h3 class="text-xl font-semibold mb-2">Full Transparency</h3><p class="text-gray-600">Every decision comes with a complete explanation.</p></div>
</div></div>

<div class="bg-gray-100 py-16">
<div class="max-w-7xl mx-auto px-4"><h2 class="text-3xl font-bold text-center mb-12">How It Works</h2>
<div class="grid md:grid-cols-4 gap-8 text-center">
<div><div class="bg-primary text-white w-16 h-16 rounded-full flex items-center justify-center text-2xl font-bold mx-auto mb-4">1</div><h3 class="font-semibold">Apply Online</h3><p class="text-gray-600 text-sm mt-2">Takes 2 minutes</p></div>
<div><div class="bg-accent text-white w-16 h-16 rounded-full flex items-center justify-center text-2xl font-bold mx-auto mb-4">2</div><h3 class="font-semibold">AI Scores You</h3><p class="text-gray-600 text-sm mt-2">Real-time risk analysis</p></div>
<div><div class="bg-blue-500 text-white w-16 h-16 rounded-full flex items-center justify-center text-2xl font-bold mx-auto mb-4">3</div><h3 class="font-semibold">Get Offer</h3><p class="text-gray-600 text-sm mt-2">Personalized rate and terms</p></div>
<div><div class="bg-purple-600 text-white w-16 h-16 rounded-full flex items-center justify-center text-2xl font-bold mx-auto mb-4">4</div><h3 class="font-semibold">Get Funded</h3><p class="text-gray-600 text-sm mt-2">Money in minutes</p></div>
</div></div></div>

<div class="bg-gradient-to-r from-primary to-blue-800 text-white py-16 text-center">
<div class="max-w-4xl mx-auto px-4">
<h2 class="text-4xl font-bold mb-4">Ready to Get Funded?</h2>
<p class="text-xl text-blue-200 mb-8">Apply in 2 minutes. Get funded in minutes.</p>
<a href="/apply" class="bg-accent hover:bg-green-700 text-white px-10 py-4 rounded-xl text-xl font-semibold inline-block shadow-lg">Check Your Rate</a>
<p class="text-sm text-blue-300 mt-4">Won\'t affect your credit score</p>
</div></div>
<footer class="bg-gray-100 py-8"><div class="text-center text-gray-500 text-sm"><p>&copy; 2026 PalmFi</p></div></footer>
</body></html>"""

LOGIN = """<!DOCTYPE html>
<html lang="en">
<head><meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1.0"><title>Sign In - PalmFi</title>
<script src="https://cdn.tailwindcss.com"></script>
<script>tailwind.config={theme:{extend:{colors:{primary:"#1a365d",accent:"#059669"}}}}</script>
<link rel="stylesheet" href="https://cdnjs.cloudflare.com/ajax/libs/font-awesome/6.5.0/css/all.min.css">
</head>
<body class="bg-gray-50 min-h-screen">
<div class="min-h-screen flex items-center justify-center py-12 px-4">
<div class="max-w-md w-full bg-white rounded-2xl shadow-xl p-8">
<div class="text-center mb-8"><div class="text-5xl mb-4"><i class="fas fa-bolt text-accent"></i></div><h1 class="text-3xl font-bold text-primary">Welcome Back</h1></div>
{% with messages = get_flashed_messages(with_categories=true) %}
{% if messages %}{% for cat,msg in messages %}
<div class="p-4 rounded-lg text-sm font-medium {{ 'bg-green-100 text-green-800' if cat=='success' else 'bg-red-100 text-red-800' if cat=='error' else 'bg-yellow-100 text-yellow-800' }} mb-4">{{ msg }}</div>
{% endfor %}{% endif %}{% endwith %}
<form method="POST" class="space-y-4">
<div><label class="block text-sm font-medium text-gray-700">Email</label><input type="email" name="email" required class="w-full mt-1 px-4 py-3 border rounded-xl focus:ring-2 focus:ring-accent"></div>
<div><label class="block text-sm font-medium text-gray-700">Password</label><input type="password" name="password" required class="w-full mt-1 px-4 py-3 border rounded-xl focus:ring-2 focus:ring-accent"></div>
<button type="submit" class="w-full bg-accent hover:bg-green-700 text-white py-4 rounded-xl font-semibold text-lg">Sign In</button>
</form>
<p class="text-center mt-6 text-gray-500">No account? <a href="/register" class="text-accent hover:underline">Create one</a></p>
</div></div></body></html>"""

REGISTER = """<!DOCTYPE html>
<html lang="en">
<head><meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1.0"><title>Create Account - PalmFi</title>
<script src="https://cdn.tailwindcss.com"></script>
<script>tailwind.config={theme:{extend:{colors:{primary:"#1a365d",accent:"#059669"}}}}</script>
<link rel="stylesheet" href="https://cdnjs.cloudflare.com/ajax/libs/font-awesome/6.5.0/css/all.min.css">
</head>
<body class="bg-gray-50 min-h-screen">
<div class="min-h-screen flex items-center justify-center py-12 px-4">
<div class="max-w-md w-full bg-white rounded-2xl shadow-xl p-8">
<div class="text-center mb-8"><h1 class="text-3xl font-bold text-primary">Join PalmFi</h1><p class="text-gray-500">AI-powered lending</p></div>
{% with messages = get_flashed_messages(with_categories=true) %}
{% if messages %}{% for cat,msg in messages %}
<div class="p-4 rounded-lg text-sm font-medium {{ 'bg-green-100 text-green-800' if cat=='success' else 'bg-red-100 text-red-800' if cat=='error' else 'bg-yellow-100 text-yellow-800' }} mb-4">{{ msg }}</div>
{% endfor %}{% endif %}{% endwith %}
<form method="POST" class="space-y-4">
<div class="grid grid-cols-2 gap-4">
<div><label class="block text-sm font-medium text-gray-700">First Name</label><input type="text" name="first_name" required class="w-full mt-1 px-4 py-3 border rounded-xl"></div>
<div><label class="block text-sm font-medium text-gray-700">Last Name</label><input type="text" name="last_name" required class="w-full mt-1 px-4 py-3 border rounded-xl"></div>
</div>
<div><label class="block text-sm font-medium text-gray-700">Email</label><input type="email" name="email" required class="w-full mt-1 px-4 py-3 border rounded-xl"></div>
<div><label class="block text-sm font-medium text-gray-700">Phone</label><input type="tel" name="phone" class="w-full mt-1 px-4 py-3 border rounded-xl"></div>
<div><label class="block text-sm font-medium text-gray-700">Password (min 6 chars)</label><input type="password" name="password" required minlength="6" class="w-full mt-1 px-4 py-3 border rounded-xl"></div>
<button type="submit" class="w-full bg-accent hover:bg-green-700 text-white py-4 rounded-xl font-semibold text-lg">Create Account</button>
</form>
<p class="text-center mt-6 text-gray-500">Already have an account? <a href="/login" class="text-accent hover:underline">Sign in</a></p>
</div></div></body></html>"""

TMPL = {
    "landing": LANDING, "login": LOGIN, "register": REGISTER,
}

def render(name, **kwargs):
    from flask import render_template_string
    t = TMPL.get(name)
    if not t: return f"<h1>Template {name} not found</h1>"
    return render_template_string(t, **kwargs)
