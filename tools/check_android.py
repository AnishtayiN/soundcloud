#!/usr/bin/env python3
"""Static checks for the Android sources - no Android SDK required.

The script parses every .java file, rebuilds the R class from res/ and verifies

  * syntax of all java files                       (javalang)
  * every R.<type>.<name> reference               (against the generated R)
  * every @string/... @drawable/... @color/...    (search in res/)
  * every view id used by findViewById(...)       (against layout @+id/...)
  * every framework class / method / field used   (against android.jar)
  * the class names of AndroidManifest.xml

Run it from the repository root:  python tools/check_android.py [path/to/android.jar]
"""
from __future__ import annotations

import os
import re
import struct
import sys
import xml.etree.ElementTree as ET
import zipfile

try:
    import javalang
except ImportError:
    print("javalang is required:  pip install javalang")
    sys.exit(2)

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ANDROID = os.path.join(ROOT, "android")
APP = os.path.join(ANDROID, "app")
SRC = os.path.join(APP, "src", "main")
RES = os.path.join(SRC, "res")
JAVA_DIR = os.path.join(SRC, "java")
MANIFEST = os.path.join(SRC, "AndroidManifest.xml")

ANDROID_NS = "{http://schemas.android.com/apk/res/android}"

PROBLEMS = []
CHECKS = [0]


def problem(message):
    PROBLEMS.append(message)
    print("  ! " + message)


def ok(message):
    CHECKS[0] += 1


# ===========================================================================
#  tiny java class file parser (constant pool + members)
# ===========================================================================
class ClassFile(object):
    def __init__(self, data):
        # constant pool slot 0 is unused, keep the list 1:1 with the indices
        self.pool = [None]
        self.this_class = ""
        self.super_class = ""
        self.interfaces = []
        self.methods = set()
        self.fields = set()
        # name -> [(parameters, return type, thrown exceptions), ...]
        self.signatures = {}
        self.method_arities = {}
        self._parse(data)

    def _utf8(self, index):
        try:
            entry = self.pool[index]
        except (IndexError, TypeError):
            return ""
        return entry if isinstance(entry, str) else ""

    def _class_name(self, index):
        """Resolves a Class constant pool entry to a dotted class name."""
        try:
            entry = self.pool[index]
        except (IndexError, TypeError):
            return ""
        if isinstance(entry, tuple) and entry[0] == "class":
            return self._utf8(entry[1])
        if isinstance(entry, str):
            return entry
        return ""

    def _parse(self, data):
        if data[:4] != b"\xca\xfe\xba\xbe":
            raise ValueError("not a class file")
        position = 8
        count, = struct.unpack_from(">H", data, position)
        position += 2
        index = 1
        while index < count:
            tag = data[position]
            position += 1
            if tag == 1:  # Utf8
                length, = struct.unpack_from(">H", data, position)
                position += 2
                self.pool.append(data[position:position + length].decode("utf-8", "replace"))
                position += length
            elif tag in (3, 4, 9, 10, 11, 12, 17, 18):
                self.pool.append(None)
                position += 4
            elif tag in (5, 6):
                # long / double take two constant pool slots
                self.pool.append(None)
                self.pool.append(None)
                position += 8
                index += 1
            elif tag == 7:  # Class -> index of the name
                self.pool.append(("class", struct.unpack_from(">H", data, position)[0]))
                position += 2
            elif tag in (8, 16, 19, 20):
                self.pool.append(None)
                position += 2
            elif tag == 15:
                self.pool.append(None)
                position += 3
            else:
                raise ValueError("unknown constant pool tag %d" % tag)
            index += 1

        def u2():
            nonlocal position
            value, = struct.unpack_from(">H", data, position)
            position += 2
            return value

        u2()  # access flags
        self.this_class = self._pool_class(self._class_name(u2()))
        self.super_class = self._pool_class(self._class_name(u2()))
        for _ in range(u2()):
            self.interfaces.append(self._pool_class(self._class_name(u2())))

        def member(target, is_method):
            nonlocal position
            flags = u2()  # access flags
            name = self._utf8(u2())
            descriptor = self._utf8(u2())
            arity = descriptor_arity(descriptor)
            parameters, returned = descriptor_types(descriptor)
            thrown = set()
            for _ in range(u2()):  # attributes
                attribute = self._utf8(u2())
                length, = struct.unpack_from(">I", data, position)
                position += 4
                if is_method and attribute == "Exceptions" and length >= 2:
                    count, = struct.unpack_from(">H", data, position)
                    for i in range(count):
                        offset = 2 + 2 * i
                        if offset + 2 > length:
                            break
                        index, = struct.unpack_from(">H", data, position + offset)
                        resolved = self._pool_class(self._class_name(index))
                        if resolved:
                            thrown.add(resolved)
                position += length
            # ACC_BRIDGE / ACC_SYNTHETIC: compiler generated helpers such as
            # StringBuilder.append(char):Appendable, which inherit the declared
            # exceptions of the interface they implement. javac never picks them
            # while a real overload exists, so they must not be used here.
            if flags & 0x1040:
                return
            target.add(name)
            if is_method:
                self.method_arities.setdefault(name, set()).add(arity)
                if parameters is not None:
                    self.signatures.setdefault(name, []).append(
                        (parameters, returned, frozenset(thrown)))

        for _ in range(u2()):
            member(self.fields, False)
        for _ in range(u2()):
            member(self.methods, True)

    def _pool_class(self, name):
        return (name or "").replace("/", ".")


def descriptor_arity(descriptor):
    """Number of parameters in a JVM method descriptor, -1 when unknown."""
    if not descriptor.startswith("("):
        return -1
    position = 1
    arity = 0
    while position < len(descriptor) and descriptor[position] != ")":
        character = descriptor[position]
        if character == "[":
            position += 1
            continue
        if character == "L":
            end = descriptor.find(";", position)
            if end < 0:
                return -1
            position = end + 1
        else:
            position += 1
        arity += 1
    return arity


PRIMITIVE_LETTERS = {"B": "byte", "C": "char", "D": "double", "F": "float",
                    "I": "int", "J": "long", "S": "short", "Z": "boolean",
                    "V": "void"}


def _field_type(descriptor, position):
    """One field descriptor -> (dotted type name, next position)."""
    if position >= len(descriptor):
        return None, position
    character = descriptor[position]
    if character == "[":
        inner, position = _field_type(descriptor, position + 1)
        return (None if inner is None else inner + "[]"), position
    if character == "L":
        end = descriptor.find(";", position)
        if end < 0:
            return None, position
        return descriptor[position + 1:end].replace("/", "."), end + 1
    if character in PRIMITIVE_LETTERS:
        return PRIMITIVE_LETTERS[character], position + 1
    return None, position + 1


def descriptor_types(descriptor):
    """(parameter types, return type) of a JVM method descriptor."""
    if not descriptor.startswith("("):
        return None, None
    position = 1
    parameters = []
    while position < len(descriptor) and descriptor[position] != ")":
        name, position = _field_type(descriptor, position)
        if name is None:
            return None, None
        parameters.append(name)
    if position >= len(descriptor):
        return None, None
    returned, _ = _field_type(descriptor, position + 1)
    return parameters, returned


class ClassPath(object):
    """Method/field lookup over android.jar (+ java.* classes)."""

    def __init__(self, jar_path):
        self.classes = {}
        with zipfile.ZipFile(jar_path) as jar:
            for name in jar.namelist():
                if not name.endswith(".class"):
                    continue
                try:
                    info = ClassFile(jar.read(name))
                except Exception:
                    continue
                self.classes[info.this_class] = info
        print("android.jar: %d classes" % len(self.classes))

    def find(self, name):
        return self.classes.get(name)

    def has_method(self, class_name, method, depth=4):
        if depth <= 0:
            return False
        info = self.classes.get(class_name)
        if info is None:
            return False
        if method in info.methods:
            return True
        if self.has_method(info.super_class, method, depth - 1):
            return True
        for interface in info.interfaces:
            if self.has_method(interface, method, depth - 1):
                return True
        return False

    def has_field(self, class_name, field, depth=4):
        if depth <= 0:
            return False
        info = self.classes.get(class_name)
        if info is None:
            return False
        if field in info.fields:
            return True
        if self.has_field(info.super_class, field, depth - 1):
            return True
        for interface in info.interfaces:
            if self.has_field(interface, field, depth - 1):
                return True
        return False

    def candidates(self, class_name, method, arity, depth=6):
        """All overloads of class.method with that arity: (types, returns, thrown)."""
        if depth <= 0:
            return []
        info = self.classes.get(class_name)
        if info is None:
            return []
        found = [signature for signature in info.signatures.get(method, ())
                 if len(signature[0]) == arity]
        if found:
            return found          # declared right here -> parents are shadowed
        inherited = self.candidates(info.super_class, method, arity, depth - 1)
        if inherited:
            return inherited
        for interface in info.interfaces:
            inherited = self.candidates(interface, method, arity, depth - 1)
            if inherited:
                return inherited
        return []

    def method_exceptions(self, class_name, method, arity, depth=6):
        """Every exception any overload with that arity may declare."""
        thrown = set()
        for _types, _returns, exceptions in self.candidates(class_name, method, arity, depth):
            thrown |= set(exceptions)
        return thrown

    def return_type(self, class_name, method, arity, depth=6):
        found = self.candidates(class_name, method, arity, depth)
        if not found:
            return None
        returns = {signature[1] for signature in found}
        return returns.pop() if len(returns) == 1 else None

    def is_unchecked(self, class_name, depth=10):
        """RuntimeException / Error (and their children) need no declaration."""
        seen = set()
        current = class_name
        while current and current not in seen and depth > 0:
            if current in ("java.lang.RuntimeException", "java.lang.Error"):
                return True
            seen.add(current)
            info = self.classes.get(current)
            if info is None:
                return False
            current = info.super_class
            depth -= 1
        return False

    WIDENING = {
        "byte": {"short", "int", "long", "float", "double", "byte"},
        "short": {"int", "long", "float", "double", "short"},
        "char": {"int", "long", "float", "double", "char"},
        "int": {"long", "float", "double", "int"},
        "long": {"float", "double", "long"},
        "float": {"double", "float"},
    }

    BOXED = {
        "boolean": "java.lang.Boolean", "byte": "java.lang.Byte", "char": "java.lang.Character",
        "short": "java.lang.Short", "int": "java.lang.Integer", "long": "java.lang.Long",
        "float": "java.lang.Float", "double": "java.lang.Double",
    }

    def accepts(self, parameter, argument):
        """Could a value of `argument` be passed as `parameter`? (None = unknown)"""
        if argument is None or parameter is None:
            return True
        if argument == parameter:
            return True
        if parameter in PRIMITIVE_LETTERS.values():
            return argument in self.WIDENING.get(parameter, ())
        if parameter == "java.lang.Object":
            return True
        if argument in PRIMITIVE_LETTERS.values():
            boxed = self.BOXED.get(argument)
            return bool(boxed) and (boxed == parameter
                                    or self.is_subtype_of(boxed, parameter))
        if argument.endswith("[]") or parameter.endswith("[]"):
            return argument == parameter
        return self.is_subtype_of(argument, parameter)

    def is_subtype_of(self, class_name, parent, depth=8):
        if class_name == parent:
            return True
        if depth <= 0:
            return False
        info = self.classes.get(class_name)
        if info is None:
            return False
        if info.super_class and self.is_subtype_of(info.super_class, parent, depth - 1):
            return True
        for interface in info.interfaces:
            if self.is_subtype_of(interface, parent, depth - 1):
                return True
        return False


# ===========================================================================
#  resources -> R class
# ===========================================================================
VALUE_TYPES = ("string", "color", "style", "dimen", "integer", "bool", "array", "attr")


def collect_resources():
    r = {kind: set() for kind in
         ("string", "color", "style", "dimen", "layout", "drawable", "mipmap", "id", "xml",
          "integer", "bool", "array")}
    for folder, _dirs, files in os.walk(RES):
        base = os.path.basename(folder)
        kind = base.split("-")[0]
        for name in files:
            stem, extension = os.path.splitext(name)
            if kind == "values" or kind.startswith("values"):
                if not extension == ".xml":
                    continue
                try:
                    root = ET.parse(os.path.join(folder, name)).getroot()
                except ET.ParseError as exc:
                    problem("values file %s does not parse: %s" % (name, exc))
                    continue
                for child in root:
                    tag = child.tag.split("}")[-1]
                    key = child.get("name")
                    if tag == "item":
                        tag = (child.get("type") or "string").strip()
                    if kind == "values" and tag in r and key:
                        r[tag].add(key)
                    elif key and tag in VALUE_TYPES:
                        r[tag].add(key)
                continue
            if kind in ("layout", "drawable", "mipmap", "xml", "menu", "anim") and extension == ".xml":
                if kind in r:
                    r[kind].add(stem)
            elif kind in ("drawable", "mipmap") and extension in (".png", ".jpg", ".webp", ".9.png"):
                r[kind].add(stem[:-4] if stem.endswith(".9") else stem)
        # ids declared in layouts
    for folder, _dirs, files in os.walk(RES):
        if not os.path.basename(folder).startswith("layout"):
            continue
        for name in files:
            if not name.endswith(".xml"):
                continue
            with open(os.path.join(folder, name), encoding="utf-8") as fh:
                text = fh.read()
            for match in re.finditer(r'@\+id/([A-Za-z_][A-Za-z0-9_]*)', text):
                r["id"].add(match.group(1))
    return r


def check_xml_references(resources):
    pattern = re.compile(r'@(?!android:|null|\+id|\*)([a-z]+)/([A-Za-z0-9_.]+)')
    for folder, _dirs, files in os.walk(RES):
        for name in files:
            if not name.endswith(".xml"):
                continue
            path = os.path.join(folder, name)
            with open(path, encoding="utf-8") as fh:
                text = fh.read()
            for match in pattern.finditer(text):
                kind, ref = match.group(1), match.group(2)
                if kind == "id":
                    continue
                if kind not in resources:
                    ok("xml kind %s" % kind)
                    continue
                if ref not in resources[kind]:
                    problem("%s: @%s/%s does not exist" % (os.path.relpath(path, ROOT), kind, ref))
    # manifest
    with open(MANIFEST, encoding="utf-8") as fh:
        text = fh.read()
    for match in pattern.finditer(text):
        kind, ref = match.group(1), match.group(2)
        if kind in resources and ref not in resources[kind]:
            problem("AndroidManifest.xml: @%s/%s does not exist" % (kind, ref))


# ===========================================================================
#  java checks
# ===========================================================================
JAVA_KEYWORDS = {"int", "long", "double", "float", "boolean", "char", "byte", "short", "void",
                 "void", "String", "Object"}


def java_files():
    for folder, _dirs, files in os.walk(JAVA_DIR):
        for name in files:
            if name.endswith(".java"):
                yield os.path.join(folder, name)


def parse_sources():
    trees = {}
    for path in java_files():
        with open(path, encoding="utf-8") as fh:
            text = fh.read()
        try:
            tree = javalang.parse.parse(text)
            ok("parsed %s" % os.path.basename(path))
        except Exception as exc:
            problem("%s: syntax error: %s" % (os.path.relpath(path, ROOT), exc))
            continue
        package = tree.package.name if tree.package else ""
        imports = {}
        for entry in tree.imports:
            imports[entry.path.split(".")[-1]] = entry.path
        classes = {}
        for _path, node in tree.filter(javalang.tree.ClassDeclaration):
            classes[node.name] = node
        for _path, node in tree.filter(javalang.tree.InterfaceDeclaration):
            classes[node.name] = node
        trees[path] = {
            "text": text, "tree": tree, "package": package,
            "imports": imports, "classes": classes,
        }
    return trees


JAVA_LANG = {
    "String", "Integer", "Long", "Boolean", "Float", "Double", "Object", "Exception",
    "Throwable", "Math", "StringBuilder", "ByteArrayOutputStream", "Thread", "Runnable",
    "System", "Character", "Iterable", "Comparable", "Number", "Class", "Override",
}

PRIMITIVES = {"int", "long", "double", "float", "boolean", "char", "byte", "short", "void"}


def type_name(type_node):
    """Notification.Builder -> Notification$Builder (arrays are skipped)"""
    if type(type_node).__name__ == "ArrayType" or getattr(type_node, "dimensions", None):
        return ""   # arrays: "x.length" is fine and x[i] has an unknown type
    name = getattr(type_node, "name", "") or ""
    sub = getattr(type_node, "sub_type", None)
    if sub is not None:
        name = name + "$" + type_name(sub)
    return name


def resolve_type(name, unit, app_classes):
    """Turns a written type name into a fully qualified class name."""
    if not name:
        return None
    name = name.split("<")[0].strip()
    if not name or name in PRIMITIVES:
        return None
    parts = name.split(".")
    first = parts[0]
    rest = parts[1:]
    base = None
    if first in app_classes:
        base = app_classes[first]
    elif first in unit["imports"]:
        base = unit["imports"][first]
    elif first in JAVA_LANG:
        base = "java.lang." + first
    elif first[:1].islower():
        base = name
    else:
        candidate = (unit["package"] + "." + first) if unit["package"] else first
        if candidate in app_classes:
            base = candidate
    if base is None:
        return None
    for part in rest:
        base = base + "$" + part
    return base


def is_framework(full):
    return (full.startswith("android.") or full.startswith("java.")
            or full.startswith("javax.") or full.startswith("org.json"))


def build_app_index(trees):
    """full class name -> declared methods/fields and their parents."""
    app_classes = {}
    for unit in trees.values():
        for name in unit["classes"]:
            full = (unit["package"] + "." + name) if unit["package"] else name
            app_classes[name] = full

    index = {}
    for unit in trees.values():
        for _p, clazz in unit["tree"].filter(javalang.tree.ClassDeclaration):
            if not clazz.name:
                continue  # anonymous class body
            full = (unit["package"] + "." + clazz.name) if unit["package"] else clazz.name
            entry = index.setdefault(full, {"methods": set(), "fields": set(),
                                            "extends": None, "implements": [],
                                            "throws": {}, "arities": {}, "returns": {}})
            for member in clazz.body or []:
                if isinstance(member, javalang.tree.MethodDeclaration):
                    entry["methods"].add(member.name)
                    arity = len(member.parameters or [])
                    entry["arities"].setdefault(member.name, set()).add(arity)
                    declared = set()
                    for written in member.throws or []:
                        resolved = resolve_type(written, unit, app_classes)
                        declared.add(resolved or written)
                    entry["returns"][(member.name, arity)] = type_name(member.return_type)
                    entry["throws"].setdefault((member.name, arity), []).append(declared)
                elif isinstance(member, javalang.tree.FieldDeclaration):
                    for declarator in member.declarators:
                        entry["fields"].add(declarator.name)
            if clazz.extends:
                entry["extends"] = resolve_type(type_name(clazz.extends), unit, app_classes)
            for interface in clazz.implements or []:
                resolved = resolve_type(type_name(interface), unit, app_classes)
                if resolved:
                    entry["implements"].append(resolved)
    return app_classes, index


def app_has(index, classpath, full, member, is_field=False, depth=6):
    """Is `member` declared on the class, its app parents or its framework parent?"""
    if depth <= 0:
        return True
    info = index.get(full)
    if info is None:
        if classpath.find(full) is None:
            return True
        return (classpath.has_field(full, member) if is_field
                else classpath.has_method(full, member))
    if member in info["fields" if is_field else "methods"]:
        return True
    parents = [info.get("extends")] + list(info.get("implements") or [])
    for parent in parents:
        if parent and app_has(index, classpath, parent, member, is_field, depth - 1):
            return True
    return False


def app_candidates(index, classpath, full, member, arity, depth=6):
    """Overloads of an own class' method, read from the sources."""
    if depth <= 0:
        return []
    info = index.get(full)
    if info is None:
        if classpath.find(full) is None:
            return []
        return classpath.candidates(full, member, arity)
    arities = info["arities"].get(member)
    if arities is not None and arity in arities:
        return [(None, info["returns"].get((member, arity)), set(thrown))
                for thrown in info["throws"].get((member, arity), [set()])]
    parents = [info.get("extends")] + list(info.get("implements") or [])
    for parent in parents:
        if parent:
            found = app_candidates(index, classpath, parent, member, arity, depth - 1)
            if found:
                return found
    if classpath.find(full) is not None:
        return classpath.candidates(full, member, arity)
    return []


def check_java(trees, classpath, resources):
    app_classes, index = build_app_index(trees)
    layout_ids = set()
    for name in os.listdir(os.path.join(RES, "layout")):
        with open(os.path.join(RES, "layout", name), encoding="utf-8") as fh:
            layout_ids |= set(re.findall(r'@\+id/([A-Za-z0-9_]+)', fh.read()))

    def check_member(relative, receiver, member, is_field=False):
        full = resolve_type(receiver, unit, app_classes)
        if full is None:
            return
        if full in index:
            if not app_has(index, classpath, full, member, is_field):
                problem("%s: %s.%s%s does not exist (own class)"
                        % (relative, receiver, member, "" if is_field else "(...)"))
            else:
                ok("%s.%s" % (full, member))
            return
        if not is_framework(full):
            return
        info = classpath.find(full)
        if info is None:
            # "SomeClass.SOME_CONSTANT.something()" -> the receiver is a field
            if "$" in full:
                parent, _, last = full.rpartition("$")
                if classpath.find(parent) is not None and classpath.has_field(parent, last):
                    return
                problem("%s: %s.%s is not a class in android.jar" % (relative, receiver, member))
                return
            problem("%s: %s is not a class in android.jar" % (relative, full))
            return
        found = (classpath.has_field(full, member) if is_field
                 else classpath.has_method(full, member))
        if not found:
            problem("%s: %s.%s%s does not exist"
                    % (relative, full, member, "" if is_field else "(...)"))
        else:
            ok("%s.%s" % (full, member))

    # ------------------------------- checked exceptions (compile errors) -----
    # javac refuses to compile code that calls a method declaring a checked
    # exception without catching it or declaring it as well. The Java compiler
    # is only reachable through CI, so the same rule is verified here:
    # method signatures are read from android.jar (Exceptions attribute) and
    # from the project sources.
    CALL_KINDS = (javalang.tree.MethodInvocation, javalang.tree.ClassCreator)
    # javalang's Node.filter() silently yields nothing for a tuple pattern, and
    # it also descends into anonymous class bodies (a different method context),
    # so the traversal is done here by hand.
    # Known limit of the parser itself: a call chained onto a constructor
    # ("new JSONObject(body).getString(...)") keeps only a text qualifier, so
    # the constructor is invisible. Assign it to a variable first.
    TYPE_DECLS = tuple(getattr(javalang.tree, kind) for kind in
                       ("ClassDeclaration", "InterfaceDeclaration", "EnumDeclaration",
                        "AnnotationDeclaration")
                       if hasattr(javalang.tree, kind))

    def collect(node, kinds, out):
        if isinstance(node, kinds):
            out.append(node)
        for attribute in type(node).attrs:
            if isinstance(node, javalang.tree.ClassCreator) and attribute == "body":
                continue          # the anonymous class body is checked on its own
            value = getattr(node, attribute, None)
            items = value if isinstance(value, (list, tuple)) else [value]
            for item in items:
                if not isinstance(item, javalang.tree.Node):
                    continue
                if isinstance(item, TYPE_DECLS):
                    continue      # nested types are visited by the class loop
                collect(item, kinds, out)

    def calls_in(node):
        found = []
        collect(node, CALL_KINDS, found)
        return found

    def kinds_in(node, kinds):
        found = []
        collect(node, kinds, found)
        return found

    def resolve_exception(name):
        """Exception names in catch/throws clauses are often unimported."""
        full = resolve_type(name, unit, app_classes)
        if full:
            return full
        if "." in name or name[:1].islower():
            return None
        for package in ("java.lang.", "java.io.", "java.util.", "java.util.concurrent."):
            if classpath.find(package + name) is not None:
                return package + name
        return None

    def catches(node, written):
        for name in written:
            full = resolve_exception(name)
            if full and (full == node or classpath.is_subtype_of(node, full)):
                return True
        return False

    def call_candidates(receiver, member, arity):
        if receiver in index or receiver in app_classes.values():
            return app_candidates(index, classpath, receiver, member, arity)
        if is_framework(receiver) and classpath.find(receiver) is not None:
            return classpath.candidates(receiver, member, arity)
        return []

    def receiver_for(invocation, locals_):
        qualifier = invocation.qualifier or ""
        if not qualifier or qualifier in ("this", "super"):
            return clazz_full or None
        if "." in qualifier or qualifier[:1].isupper():
            return resolve_type(qualifier, unit, app_classes)
        return resolve_type(locals_.get(qualifier, ""), unit, app_classes)

    def return_type_of(receiver, member, arity):
        for _types, returned, _thrown in call_candidates(receiver, member, arity):
            if returned:
                return resolve_type(returned, unit, app_classes) or returned
        return None

    def argument_type(node, locals_):
        """Static type of an argument, when it can be told without inference."""
        kind = type(node).__name__
        if kind == "Literal":
            value = node.value
            if value == "null":
                return None
            if value.startswith('"'):
                return "java.lang.String"
            if value.startswith("'"):
                return "char"
            if isinstance(value, str):
                lowered = value.lower()
                if lowered.endswith("f"):
                    return "float"
                if lowered.endswith("l"):
                    return "long"
                if "." in value or "e" in lowered:
                    return "double"
                return "int"
            if isinstance(value, bool):
                return "boolean"
            return None
        if kind == "MemberReference":
            if node.qualifier:
                return None
            return locals_.get(node.member)
        if kind == "ClassCreator":
            return resolve_type(type_name(node.type), unit, app_classes)
        if kind == "Cast":
            return resolve_type(type_name(node.type), unit, app_classes)
        if kind == "This":
            return clazz_full or None
        if kind == "TernaryExpression":
            left = argument_type(node.if_true, locals_)
            right = argument_type(node.if_false, locals_)
            return left if left and left == right else None
        if kind == "BinaryOperation":
            for operand in (node.operandl, node.operandr):
                if argument_type(operand, locals_) == "java.lang.String":
                    return "java.lang.String"
            return None
        if kind == "MethodInvocation":
            receiver = receiver_for(node, locals_)
            if receiver:
                return return_type_of(receiver, node.member, len(node.arguments or []))
        return None

    def check_throws(caller, receiver, member, context, arguments):
        candidates = call_candidates(receiver, member, len(arguments))
        if not candidates:
            return
        # keep only the overloads the compiler could actually pick here
        types = [argument_type(argument, context["locals"]) for argument in arguments]
        narrowed = []
        for parameter_types, returned, thrown in candidates:
            expected = parameter_types if parameter_types is not None else [None] * len(types)
            if len(expected) != len(types):
                continue
            if all(classpath.accepts(parameter, argument)
                   for parameter, argument in zip(expected, types)):
                narrowed.append((returned, thrown))
        if narrowed:
            candidates = narrowed
        # an unchecked exception needs no declaration; a missing exception in one
        # candidate means the compiler may simply pick that candidate
        common = None
        for candidate in candidates:
            thrown = candidate[-1]
            checked = {name for name in thrown if not classpath.is_unchecked(name)}
            common = checked if common is None else (common & checked)
        if not common:
            return
        for name in sorted(common):
            if catches(name, context["caught"].get(id(caller), ())):
                continue
            if catches(name, context["declared"]):
                continue
            problem("%s: line %s: %s.%s(...) throws %s: catch it or declare it"
                    % (relative, (caller.position.line if caller.position else "?"),
                       receiver, member, name))
            return
        ok("%s.%s checked exceptions" % (receiver, member))

    for path, unit in trees.items():
        relative = os.path.relpath(path, ROOT)
        text = unit["text"]
        tree = unit["tree"]

        # ------------------------------------------------------ R.* usage ---
        for match in re.finditer(r'(?<!android\.)\bR\.([a-z]+)\.([A-Za-z0-9_]+)', text):
            kind, name = match.group(1), match.group(2)
            if kind not in resources:
                problem("%s: R.%s is not a resource type" % (relative, kind))
            elif name not in resources[kind]:
                problem("%s: R.%s.%s does not exist" % (relative, kind, name))
            else:
                ok("R.%s.%s" % (kind, name))

        for match in re.finditer(r'android\.R\.([a-z]+)\.([A-Za-z0-9_]+)', text):
            kind, name = match.group(1), match.group(2)
            if not classpath.has_field("android.R$" + kind, name):
                problem("%s: android.R.%s.%s does not exist" % (relative, kind, name))

        # --------------------------------------------- findViewById ids -----
        for match in re.finditer(r'findViewById\(R\.id\.([A-Za-z0-9_]+)\)', text):
            if match.group(1) not in layout_ids:
                problem("%s: findViewById(R.id.%s) has no @+id in the layouts"
                        % (relative, match.group(1)))

        # ------------------------------------------------- import sanity ----
        for import_node in tree.imports:
            full = import_node.path
            if full.startswith("com.soundcloudx"):
                continue
            if is_framework(full) and classpath.find(full) is None:
                problem("%s: import %s is not in android.jar" % (relative, full))

        # --------------------------------------- classes used in the code ---
        for _p, node in tree.filter(javalang.tree.ClassCreator):
            created = type_name(node.type)
            full = resolve_type(created, unit, app_classes)
            if full is None:
                continue
            if full in index or full in app_classes.values():
                continue
            if not is_framework(full):
                continue
            if classpath.find(full) is None:
                problem("%s: new %s() - class not found in android.jar" % (relative, created))
            else:
                ok("new %s" % created)

        for _p, node in tree.filter(javalang.tree.ReferenceType):
            if node.sub_type is not None and not getattr(node, "arguments", None):
                continue

        # ---------------------------------------------- static members ------
        for _p, node in tree.filter(javalang.tree.MethodInvocation):
            qualifier = node.qualifier or ""
            if not qualifier or not qualifier[:1].isupper():
                continue
            check_member(relative, qualifier, node.member)

        for _p, node in tree.filter(javalang.tree.MemberReference):
            qualifier = node.qualifier or ""
            if not qualifier or not qualifier[:1].isupper():
                continue
            check_member(relative, qualifier, node.member, is_field=True)

        # ------- instance calls on typed local variables and class fields ---
        for _p, clazz in tree.filter(javalang.tree.ClassDeclaration):
            class_fields = {}
            for member in clazz.body or []:
                if isinstance(member, javalang.tree.FieldDeclaration):
                    declared_type = type_name(member.type)
                    for declarator in member.declarators:
                        class_fields[declarator.name] = declared_type
            for method in clazz.methods or []:
                locals_ = dict(class_fields)
                for parameter in method.parameters or []:
                    locals_[parameter.name] = type_name(parameter.type)
                for _q, declaration in method.filter(javalang.tree.VariableDeclaration):
                    declared_type = type_name(declaration.type)
                    for declarator in declaration.declarators:
                        locals_[declarator.name] = declared_type
                for _q, invocation in method.filter(javalang.tree.MethodInvocation):
                    qualifier = invocation.qualifier or ""
                    if not qualifier or qualifier[:1].isupper() or "." in qualifier:
                        continue
                    declared = locals_.get(qualifier)
                    if not declared:
                        continue
                    full = resolve_type(declared, unit, app_classes)
                    if full is None:
                        continue
                    if full in index:
                        if not app_has(index, classpath, full, invocation.member):
                            problem("%s: %s.%s(...) does not exist (own class %s)"
                                    % (relative, qualifier, invocation.member, full))
                        else:
                            ok("%s.%s" % (full, invocation.member))
                        continue
                    if not is_framework(full) or classpath.find(full) is None:
                        continue
                    if not classpath.has_method(full, invocation.member):
                        problem("%s: %s.%s(...) does not exist (%s)"
                                % (relative, qualifier, invocation.member, full))
                    else:
                        ok("%s.%s" % (full, invocation.member))
                for _q, reference in method.filter(javalang.tree.MemberReference):
                    qualifier = reference.qualifier or ""
                    if not qualifier or qualifier[:1].isupper() or "." in qualifier:
                        continue
                    declared = locals_.get(qualifier)
                    if not declared:
                        continue
                    full = resolve_type(declared, unit, app_classes)
                    if full is None:
                        continue
                    if full in index:
                        if not app_has(index, classpath, full, reference.member, True):
                            problem("%s: %s.%s (field) does not exist (own class %s)"
                                    % (relative, qualifier, reference.member, full))
                        else:
                            ok("%s.%s" % (full, reference.member))
                        continue
                    if not is_framework(full) or classpath.find(full) is None:
                        continue
                    if not classpath.has_field(full, reference.member):
                        problem("%s: %s.%s (field) does not exist (%s)"
                                % (relative, qualifier, reference.member, full))
                    else:
                        ok("%s.%s" % (full, reference.member))

        # -------------------------------- checked exceptions (compile risk) --
        for _p, clazz in tree.filter(javalang.tree.ClassDeclaration):
            clazz_full = ((unit["package"] + "." + clazz.name)
                          if unit["package"] and clazz.name else (clazz.name or ""))
            class_fields = {}
            for member in clazz.body or []:
                if isinstance(member, javalang.tree.FieldDeclaration):
                    declared_type = type_name(member.type)
                    for declarator in member.declarators:
                        class_fields[declarator.name] = declared_type
            for member in clazz.body or []:
                if isinstance(member, javalang.tree.MethodDeclaration):
                    body, declared = member.body, list(member.throws or [])
                elif isinstance(member, javalang.tree.ConstructorDeclaration):
                    body, declared = member.body, list(member.throws or [])
                else:
                    continue
                if not body:
                    continue
                locals_ = dict(class_fields)
                for parameter in member.parameters or []:
                    locals_[parameter.name] = type_name(parameter.type)
                for declaration in kinds_in(member, javalang.tree.VariableDeclaration):
                    declared_type = type_name(declaration.type)
                    for declarator in declaration.declarators:
                        locals_[declarator.name] = declared_type
                for resource in kinds_in(member, javalang.tree.TryResource):
                    locals_[resource.name] = type_name(resource.type)
                caught = {}
                for try_node in kinds_in(member, javalang.tree.TryStatement):
                    written = set()
                    for clause in try_node.catches or []:
                        written |= set(clause.parameter.types or [])
                    if not written:
                        continue
                    protected = list(try_node.block or [])
                    # Resource initializers are inside the implicit try/finally
                    # generated for try-with-resources, including its close().
                    for resource in try_node.resources or []:
                        if resource.value is not None:
                            protected.append(resource.value)
                    for statement in protected:
                        for node in calls_in(statement):
                            caught.setdefault(id(node), set()).update(written)
                context = {"declared": declared, "caught": caught, "locals": locals_}
                for invocation in kinds_in(member, javalang.tree.MethodInvocation):
                    receiver = receiver_for(invocation, locals_)
                    if receiver:
                        check_throws(invocation, receiver, invocation.member, context,
                                     invocation.arguments or [])
                for creator in kinds_in(member, javalang.tree.ClassCreator):
                    receiver = resolve_type(type_name(creator.type), unit, app_classes)
                    if receiver:
                        check_throws(creator, receiver, "<init>", context,
                                     creator.arguments or [])


def check_manifest(trees):
    with open(MANIFEST, encoding="utf-8") as fh:
        manifest = fh.read()
    # The historical regex-only checks silently accepted malformed XML.
    try:
        document = ET.fromstring(manifest)
    except ET.ParseError as error:
        problem("AndroidManifest.xml is not valid XML: %s" % error)
        return
    application = document.find("application")
    if application is None:
        problem("manifest has no application")
        return
    for key, expected in (("supportsRtl", "true"), ("allowBackup", "false")):
        if application.get(ANDROID_NS + key) != expected:
            problem("application must declare android:%s=%s" % (key, expected))
        else:
            ok("manifest " + key)
    receivers = application.findall("receiver")
    media = next((node for node in receivers if node.get(ANDROID_NS + "name", "").endswith("MediaBtnReceiver")), None)
    if media is None:
        problem("MediaBtnReceiver is not registered")
    else:
        if media.get(ANDROID_NS + "exported") != "false":
            problem("MediaBtnReceiver must be non-exported")
        actions = [node.get(ANDROID_NS + "name") for node in media.findall("intent-filter/action")]
        if "android.intent.action.MEDIA_BUTTON" not in actions:
            problem("MediaBtnReceiver lacks MEDIA_BUTTON filter")
        else:
            ok("private media-button receiver")
    service = next((node for node in application.findall("service") if node.get(ANDROID_NS + "name") == ".PlayerService"), None)
    if service is None or service.get(ANDROID_NS + "exported") != "false":
        problem("PlayerService must exist and be non-exported")
    for match in re.finditer(r'android:name="\.?([A-Za-z0-9_.$]+)"', manifest):
        name = match.group(1)
        if name.startswith("android.permission") or name.startswith("android.intent"):
            continue
        if name.endswith("MediaBtnReceiver") or name.endswith("MainActivity") \
                or name.endswith("LoginActivity") or name.endswith("PlayerService"):
            simple = name.split(".")[-1]
            found = any(simple in unit["classes"] for unit in trees.values())
            if not found:
                problem("AndroidManifest.xml references %s but no such java class" % name)
            else:
                ok("manifest %s" % name)
    for permission in re.findall(r'android:name="(android\.permission\.[A-Z_]+)"', manifest):
        ok("permission %s" % permission)
    if 'android:foregroundServiceType="mediaPlayback"' not in manifest:
        problem("the player service must declare foregroundServiceType=mediaPlayback (Android 14+)")


def check_reliability():
    # Explicit resource parity protects the Persian default from accidental
    # English replacement during future module splits.
    def strings(folder):
        path = os.path.join(RES, folder, "strings.xml")
        root = ET.parse(path).getroot()
        return {node.get("name"): node.text or "" for node in root.findall("string")}
    default, persian, english = strings("values"), strings("values-fa"), strings("values-en")
    for name, text in default.items():
        if name not in persian or persian[name] != text:
            problem("Persian default string changed or missing: " + name)
        else:
            ok("fa string " + name)
        if name not in english:
            problem("English translation missing: " + name)
    expectations = {
        "Art.java": ("MEMORY_BUDGET", "getAllocationByteCount", "inJustDecodeBounds", "inSampleSize"),
        "SearchController.java": ("requestGeneration != generation",),
        "PlayerBar.java": ("Context.RECEIVER_NOT_EXPORTED",),
        "MainActivity.java": ("Context.RECEIVER_NOT_EXPORTED",),
        "PlayerService.java": ("audio focus denied", "STATE_ERROR", "MediaBtnReceiver.class"),
        "Prefs.java": ("EncryptedSharedPreferences", "allow_roaming"),
        "Downloader.java": ("mimeFor", "setAllowedOverRoaming(prefs.allowRoaming())", "track_id"),
        "DownloadCompletionReceiver.java": ("IS_PENDING", "STATUS_SUCCESSFUL"),
        "Track.java": ('"track_authorization"', '"download_url"'),
    }
    for filename, tokens in expectations.items():
        text = open(os.path.join(JAVA_DIR, "com", "soundcloudx", "app", filename), encoding="utf-8").read()
        for token in tokens:
            if token not in text:
                problem("%s missing reliability invariant %s" % (filename, token))
            else:
                ok(filename + " " + token)
    for filename in ("ScApi.java", "PlayerService.java"):
        text = open(os.path.join(JAVA_DIR, "com", "soundcloudx", "app", filename), encoding="utf-8").read()
        if re.search(r"catch\s*\([^)]*\b(?:ignored|ignore)\b[^)]*\)\s*\{\s*\}", text):
            problem(filename + " contains a silent ignored catch")
        else:
            ok(filename + " no silent ignored catch")


def main(argv):
    jar = argv[1] if len(argv) > 1 else os.environ.get("ANDROID_JAR", "")
    if not jar or not os.path.isfile(jar):
        for candidate in ("/usr/share/android/android.jar", "android.jar",
                          os.path.join(ROOT, "tools", "android.jar")):
            if os.path.isfile(candidate):
                jar = candidate
                break
    if not jar or not os.path.isfile(jar):
        print("android.jar not found - pass it as an argument or set ANDROID_JAR")
        return 2

    print("== resources ==")
    resources = collect_resources()
    check_xml_references(resources)
    print("   %d names in R" % sum(len(v) for v in resources.values()))

    print("== reliability / localization invariants ==")
    check_reliability()
    print("== java ==")
    trees = parse_sources()
    print("   %d source files" % len(trees))

    print("== framework ==")
    classpath = ClassPath(jar)
    check_java(trees, classpath, resources)
    check_manifest(trees)

    print("\n%d checks, %d problems" % (CHECKS[0], len(PROBLEMS)))
    if PROBLEMS:
        print("\nproblems:")
        for item in PROBLEMS[:60]:
            print(" - " + item)
        return 1
    print("all good ✔")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
