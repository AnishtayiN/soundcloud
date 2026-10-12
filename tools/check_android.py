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

        def member(target):
            nonlocal position
            u2()  # access flags
            name = self._utf8(u2())
            u2()  # descriptor
            for _ in range(u2()):  # attributes
                u2()
                length, = struct.unpack_from(">I", data, position)
                position += 4 + length
            target.add(name)

        for _ in range(u2()):
            member(self.fields)
        for _ in range(u2()):
            member(self.methods)

    def _pool_class(self, name):
        return (name or "").replace("/", ".")


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
                                            "extends": None, "implements": []})
            for member in clazz.body or []:
                if isinstance(member, javalang.tree.MethodDeclaration):
                    entry["methods"].add(member.name)
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


def check_manifest(trees):
    with open(MANIFEST, encoding="utf-8") as fh:
        manifest = fh.read()
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
