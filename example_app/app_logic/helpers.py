# simple functions for runtime tracking

from modulens import feature_flag

@feature_flag("new_checkout_ui")
def checkout_config():
    return True

def greet_user(name):
    do_stuff()
    return f"Hello, {name}!"

def farewell():
    return "Goodbye!"

def do_stuff():
    x = 1+1

def dead():
    print("Im a Zombie")