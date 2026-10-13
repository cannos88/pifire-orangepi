"""Bozza di interfaccia moderna per PiFire su ILI9341 320x240.
Disegna in supersampling (S volte) e riduce a 320x240 per avere bordi morbidi."""
import os, sys, math
from PIL import Image, ImageDraw, ImageFont

HERE = os.path.dirname(os.path.abspath(__file__))
FONTS = os.path.join(HERE, 'fonts')
FA = os.path.join(HERE, '..', '..', 'static', 'font', 'FA-Free-Solid.otf')
W, H, S = 320, 240, 4

# Palette
BG      = (12, 14, 15)
CARD    = (24, 27, 29)
LINE    = (44, 48, 51)
TEXT    = (244, 241, 236)
MUTED   = (135, 141, 146)
EMBER   = (255, 110, 30)
EMBER_D = (90, 40, 14)
OK      = (88, 200, 120)

def font(name, px):
    return ImageFont.truetype(os.path.join(FONTS, name) if not name.startswith('/') else name, int(px * S))

F_BIG   = lambda px: font('BarlowCondensed-SemiBold.ttf', px)
F_MED   = lambda px: font('BarlowCondensed-Medium.ttf', px)
F_UI    = lambda px: font('Barlow-SemiBold.ttf', px)
F_UIR   = lambda px: font('Barlow-Medium.ttf', px)
F_ICON  = lambda px: font(FA, px)

class Canvas:
    def __init__(self):
        self.im = Image.new('RGB', (W * S, H * S), BG)
        self.d = ImageDraw.Draw(self.im)
    def s(self, *v): return [x * S for x in v]
    def rrect(self, x0, y0, x1, y1, r, fill=None, outline=None, width=1):
        self.d.rounded_rectangle(self.s(x0, y0, x1, y1), radius=r * S, fill=fill, outline=outline, width=int(width * S))
    def text(self, x, y, t, f, fill, anchor='la'):
        self.d.text((x * S, y * S), t, font=f, fill=fill, anchor=anchor)
    def tw(self, t, f): return self.d.textlength(t, font=f) / S
    def arc(self, box, a0, a1, fill, width):
        self.d.arc(self.s(*box), a0, a1, fill=fill, width=int(width * S))
    def circle(self, cx, cy, r, fill):
        self.d.ellipse(self.s(cx - r, cy - r, cx + r, cy + r), fill=fill)
    def done(self):
        return self.im.resize((W, H), Image.LANCZOS)

def status_bar(c, mode_label, timer, fan=True, auger=False, igniter=False, smoke_plus=False):
    # Modalità: pallino arancione + etichetta
    c.circle(12, 14, 3.5, EMBER)
    c.text(21, 14, mode_label, F_UI(12), TEXT, 'lm')
    # Timer cottura al centro
    c.text(160, 14, '', F_ICON(10), MUTED, 'mm')
    c.text(168, 14, timer, F_MED(15), TEXT, 'lm')
    # Uscite attive a destra: accese in arancio, spente in grigio
    x = 308
    for ch, on in (('', True), ('', igniter), ('', auger), ('', fan)):
        c.text(x, 14, ch, F_ICON(10), (EMBER if on and ch != '' else (TEXT if ch == '' else LINE)), 'rm')
        x -= 20
    c.d.line(c.s(0, 28, W, 28), fill=LINE, width=S)

def grill_block(c, temp, target, smoke_plus):
    c.text(14, 40, 'GRILL', F_UI(11), MUTED, 'la')
    t = str(temp)
    f = F_BIG(84)
    c.text(10, 118, t, f, TEXT, 'ls')
    tw = c.tw(t, f)
    c.text(14 + tw, 62, '°C', F_MED(20), MUTED, 'la')
    # Barra di avvicinamento al target
    frac = max(0, min(1, temp / max(target, 1)))
    c.rrect(14, 128, 186, 132, 2, fill=LINE)
    c.rrect(14, 128, 14 + 172 * min(frac, 1), 132, 2, fill=EMBER)
    # Colonna destra: target e Smoke+
    c.rrect(200, 40, 308, 104, 10, fill=CARD)
    c.text(212, 50, 'TARGET', F_UI(10), MUTED, 'la')
    c.text(212, 96, f'{target}°', F_BIG(40), EMBER, 'ls')
    if smoke_plus:
        c.rrect(200, 112, 308, 134, 11, outline=LINE, width=1)
        c.text(214, 123, '', F_ICON(10), TEXT, 'lm')
        c.text(230, 123, 'Smoke+ attivo', F_UIR(11), TEXT, 'lm')

def probe_card(c, x0, name, temp, target):
    x1, y0, y1 = x0 + 145, 146, 230
    c.rrect(x0, y0, x1, y1, 10, fill=CARD)
    c.text(x0 + 12, y0 + 10, name.upper(), F_UI(10), MUTED, 'la')
    reached = temp >= target
    c.text(x0 + 10, y0 + 62, f'{temp}°', F_BIG(46), OK if reached else TEXT, 'ls')
    tt = f'{target}°'
    c.text(x1 - 12, y0 + 58, tt, F_MED(16), MUTED, 'rs')
    c.text(x1 - 16 - c.tw(tt, F_MED(16)), y0 + 52, chr(0xf140), F_ICON(9), MUTED, 'rm')
    frac = max(0, min(1, temp / target))
    c.rrect(x0 + 12, y1 - 14, x1 - 12, y1 - 10, 2, fill=LINE)
    c.rrect(x0 + 12, y1 - 14, x0 + 12 + (x1 - x0 - 24) * frac, y1 - 10, 2, fill=OK if reached else EMBER)

def screen_home():
    c = Canvas()
    status_bar(c, 'MANTENIMENTO', '2:14', fan=True, auger=True, igniter=False, smoke_plus=True)
    grill_block(c, 112, 110, True)
    probe_card(c, 10, 'Spalla', 71, 93)
    probe_card(c, 165, 'Petto', 74, 74)
    return c.done()

def screen_setpoint(value=110, vmin=50, vmax=260):
    c = Canvas()
    c.text(14, 14, '', F_ICON(10), MUTED, 'lm')
    c.text(30, 14, 'Temperatura grill', F_UI(12), TEXT, 'lm')
    c.d.line(c.s(0, 28, W, 28), fill=LINE, width=S)
    cx, cy, r = 160, 138, 82
    a0, a1 = 135, 405  # arco di 270°
    box = (cx - r, cy - r, cx + r, cy + r)
    c.arc(box, a0, a1, LINE, 10)
    frac = (value - vmin) / (vmax - vmin)
    c.arc(box, a0, a0 + 270 * frac, EMBER, 10)
    # pomello sulla posizione attuale
    ang = math.radians(a0 + 270 * frac)
    c.circle(cx + r * math.cos(ang), cy + r * math.sin(ang), 8, TEXT)
    c.text(cx, cy + 8, str(value), F_BIG(72), TEXT, 'ms')
    c.text(cx, cy + 28, '°C', F_MED(18), MUTED, 'mm')
    c.text(cx - r + 4, cy + r - 18, f'{vmin}°', F_MED(13), MUTED, 'mm')
    c.text(cx + r - 4, cy + r - 18, f'{vmax}°', F_MED(13), MUTED, 'mm')
    c.text(cx, 226, 'Ruota per regolare  ·  Premi per confermare', F_UIR(10), MUTED, 'mm')
    return c.done()

def screen_menu(sel=1):
    c = Canvas()
    c.text(14, 14, '', F_ICON(10), MUTED, 'lm')
    c.text(30, 14, 'Menu', F_UI(12), TEXT, 'lm')
    c.text(306, 14, 'MANTENIMENTO 110°', F_UIR(10), MUTED, 'rm')
    c.d.line(c.s(0, 28, W, 28), fill=LINE, width=S)
    items = [('', 'Temperatura grill', '110°'), ('', 'Affumicatura', ''),
             ('', 'Smoke+', 'ON'), ('', 'Spegnimento', ''), ('', 'Rete e QR code', '')]
    y = 36
    for i, (ic, label, val) in enumerate(items):
        on = i == sel
        if on:
            c.rrect(8, y, 312, y + 34, 9, fill=CARD)
        c.text(26, y + 17, ic, F_ICON(13), EMBER if on else MUTED, 'mm')
        c.text(44, y + 17, label, F_UI(14) if on else F_UIR(14), TEXT if on else MUTED, 'lm')
        if val:
            c.text(300, y + 17, val, F_MED(15), EMBER if on else MUTED, 'rm')
        elif on:
            c.text(300, y + 17, '', F_ICON(10), MUTED, 'rm')
        y += 38
    return c.done()

if __name__ == '__main__':
    out = sys.argv[1] if len(sys.argv) > 1 else HERE
    shots = [screen_home(), screen_menu(), screen_setpoint()]
    for n, im in zip(('home', 'menu', 'setpoint'), shots):
        im.save(os.path.join(out, f'moderno_{n}.png'))
    gap = 24
    sheet = Image.new('RGB', (W * 3 + gap * 2, H), (40, 42, 44))
    for i, im in enumerate(shots):
        sheet.paste(im, (i * (W + gap), 0))
    sheet.resize((sheet.width * 2, sheet.height * 2), Image.NEAREST).save(os.path.join(out, 'moderno_anteprima.png'))
    print('ok')
