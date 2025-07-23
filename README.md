# 🌀 Modulens

🔍 Runtime-based function usage tracker for Python.  
Find unused (dead) code in your project — no static analysis required.

## 🧠 What Is Modulens?

Modulens is a lightweight SDK that tracks which functions are actually executed during runtime. It helps developers identify:

- ✅ Which functions are used
- 🪦 Which ones are never called (dead code)
- 📦 How many times each function is invoked

**Use cases:**

- Refactoring large projects
- Auditing stale codebases
- Trimming unused endpoints
- Understanding runtime coverage in dynamic frameworks (e.g. Flask, FastAPI)

## ⚡️ Features

- ✅ Tracks real function calls — no guesswork
- 🧹 Identifies dead code
- 📄 Flushes to local JSON file (`modulens_output/runtime_report.json`)
- ⛔️ Ignores stdlib, site-packages, and virtualenvs automatically
- 🔍 Works with any Python app: Flask, FastAPI, CLI tools, etc.

## 🚀 Quickstart

### 📦 Install

```bash
pip install modulens
```

### 🧩 Add to your app

Add this to the very top of your entry file (e.g. `main.py` or `app.py`):

```python
import modulens

modulens.start()
```

That’s it. Run your app normally.


## 🧾 Output Example

After your program exits, Modulens will write a report to:

```
modulens_output/runtime_report.json
```

Example output:

```json
{
  "called_functions": {
    "app.views.home": 4,
    "app.utils.ping": 2
  },
  "dead_functions": [
    "app.tasks.cleanup",
    "app.admin.unused_dashboard"
  ]
}
```


## 🛠 Advanced Options

### Selective tracking

Only include specific modules:

```python
modulens.start(include=["myapp", "api"])
```

Exclude noisy modules:

```python
modulens.start(exclude=["myapp.migrations", "tests"])
```


## 💡 How It Works

Modulens uses Python's built-in `sys.setprofile()` and `inspect` to:

1. Hook into function calls at runtime
2. Track which functions are called (and how often)
3. On shutdown, compare to all defined functions in loaded modules
4. Output which functions were **never** called — i.e., likely dead code


## 📂 Output Location

All data is written to:

```
modulens_output/runtime_report.json
```


## ⚠️ Limitations

- Requires the code to actually run to track usage
- Doesn’t detect calls inside modules that were never imported
- Doesn’t distinguish test coverage from production usage (yet)


## 🧪 Works With

- ✅ Pure Python scripts
- ✅ Flask, FastAPI, Django
- ✅ CLI tools, cron jobs, schedulers
- ❌ Not for Cython, compiled extensions, or native C functions


## 📖 License

MIT — free to use, modify, and contribute.


## ✨ Stay in the Loop

Want access to the hosted dashboard beta or to contribute?

📬 [Email us](mailto:founder@modulens.io)  
🌐 [Website coming soon](https://modulens.io)  

---

> Modulens – *see what code actually runs.*
