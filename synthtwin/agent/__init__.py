"""Chat-driven study agent: goal -> related studies -> simulation stack -> benchmark
sample -> benchmark -> the user's case -> recipe -> robot.

The implementation moved: the orchestrator is synthtwin/core/engine.py, one folder
per UI step is under synthtwin/steps/, and shared modules are in synthtwin/core/.
The modules here are import-path shims so existing scripts keep working.
"""
