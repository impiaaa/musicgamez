# https://github.com/sqlalchemy/sqlalchemy/wiki/Views

from sqlalchemy import *
from sqlalchemy.ext import compiler
from sqlalchemy.schema import DDLElement
from sqlalchemy.sql import table


class CreateView(DDLElement):
    def __init__(self, name, selectable, material=False, temporary=False):
        self.name = name
        self.selectable = selectable
        self.material = material
        self.temporary = temporary


class DropView(DDLElement):
    def __init__(self, name):
        self.name = name


@compiler.compiles(CreateView)
def compile(element, compiler, **kw):
    return "CREATE %s%sVIEW %s AS %s" % (
        "TEMPORARY " if element.temporary else "",
        "MATERIALIZED " if element.material else "",
        element.name,
        compiler.sql_compiler.process(element.selectable, literal_binds=True))


@compiler.compiles(DropView)
def compile(element, compiler, **kw):
    return "DROP VIEW %s" % (element.name)


def view(name, metadata, selectable, material=False):
    t = table(name)

    for c in selectable.c:
        c._make_proxy(t)

    CreateView(name, selectable, material).execute_at('after-create', metadata)
    DropView(name).execute_at('before-drop', metadata)
    return t
