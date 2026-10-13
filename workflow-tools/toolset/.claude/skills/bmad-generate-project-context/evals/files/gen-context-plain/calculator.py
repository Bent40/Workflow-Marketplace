# calculator.py
# Plain, idiomatic Python. Nothing unusual here: no custom layering, no
# project-specific conventions, no surprising patterns. Just simple functions.


def add(a, b):
    return a + b


def subtract(a, b):
    return a - b


def multiply(a, b):
    return a * b


def divide(a, b):
    if b == 0:
        raise ZeroDivisionError("cannot divide by zero")
    return a / b
