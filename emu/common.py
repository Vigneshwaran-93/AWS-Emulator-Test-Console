"""Helpers shared by service modules: field/action builders, sample data."""
import io
import json
import zipfile


def F(name, label=None, default="", type="text", options=None, help="", sync=False, rows=4, sample=None, placeholder=""):
    """Form field. type: text | textarea | number | select | checkbox | file"""
    return {"name": name, "label": label or name.replace("_", " ").title(), "default": default, "type": type,
            "options": options or [], "help": help, "sync": sync, "rows": rows, "sample": sample, "placeholder": placeholder}


def action(id, title, desc, fields, fn):
    return {"id": id, "title": title, "desc": desc, "fields": fields, "fn": fn}


def scenario(id, title, desc, fields, fn):
    return {"id": id, "title": title, "desc": desc, "fields": fields, "fn": fn}


def service(id, title, group, boto, desc, probe, actions, scenarios=(), docs=""):
    s = {"id": id, "title": title, "group": group, "boto": boto, "desc": desc, "probe": probe,
         "actions": list(actions), "scenarios": list(scenarios), "docs": docs}
    for it in s["actions"] + s["scenarios"]:
        it["svc"] = id
        it["svc_title"] = title
    return s


def sample_image(kind="invoice"):
    """Generate a PNG test image with Pillow (so Textract / Rekognition have something real to look at)."""
    from PIL import Image, ImageDraw, ImageFont
    try:
        font = ImageFont.truetype("arial.ttf", 22)
        big = ImageFont.truetype("arial.ttf", 34)
    except Exception:  # noqa
        font = big = ImageFont.load_default()
    if kind == "invoice":
        im = Image.new("RGB", (760, 520), "white")
        d = ImageDraw.Draw(im)
        d.text((40, 30), "ACME Corp. INVOICE", fill="black", font=big)
        lines = ["Invoice No: INV-2026-1042", "Date: 2026-11-20", "Bill To: Jane Doe, 42 Elm Street, Seattle WA",
                 "", "Item                 Qty     Price", "Widget A               2     $24.00",
                 "Widget B               1     $80.50", "", "Total Due: $128.50", "Contact: jane.doe@example.com  +1 206 555 0142"]
        y = 110
        for ln in lines:
            d.text((40, y), ln, fill="black", font=font)
            y += 36
        d.rectangle((30, 100, 730, 480), outline="black")
    else:
        im = Image.new("RGB", (760, 520), (135, 190, 235))
        d = ImageDraw.Draw(im)
        d.rectangle((0, 380, 760, 520), fill=(70, 150, 70))           # grass
        d.ellipse((600, 40, 700, 140), fill=(255, 220, 40))            # sun
        d.rectangle((200, 250, 420, 400), fill=(190, 90, 60))          # house
        d.polygon([(180, 250), (310, 160), (440, 250)], fill=(110, 40, 30))
        d.rectangle((290, 320, 340, 400), fill=(80, 50, 30))
        d.ellipse((500, 260, 580, 340), fill=(250, 210, 170))          # face
        d.ellipse((520, 285, 530, 295), fill="black")
        d.ellipse((550, 285, 560, 295), fill="black")
        d.arc((520, 300, 560, 330), 10, 170, fill="black", width=3)
        d.text((40, 30), "SUMMER SALE 50% OFF", fill="white", font=big)
    buf = io.BytesIO()
    im.save(buf, "PNG")
    return buf.getvalue()


def make_zip(filename, code):
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr(filename, code)
    return buf.getvalue()


def account_id(c):
    return c("sts").get_caller_identity()["Account"]


def wait_table(c, name):
    """DynamoDB creates tables asynchronously (CREATING -> ACTIVE)."""
    c("dynamodb").get_waiter("table_exists").wait(TableName=name, WaiterConfig={"Delay": 1, "MaxAttempts": 30})
    return "ACTIVE"


def wait_lambda(c, name):
    """Lambda functions start in Pending state."""
    c("lambda").get_waiter("function_active_v2").wait(FunctionName=name, WaiterConfig={"Delay": 1, "MaxAttempts": 30})
    return "Active"


def jdump(o):
    return json.dumps(o, indent=2)
