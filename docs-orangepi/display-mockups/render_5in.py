"""
Bozze dell'interfaccia per il display HDMI 5" MPI5006 (IPS 1024x600, area
visibile 108 x 64,8 mm, circa 9,5 pixel per mm).

Il disegno usa unita' di progetto: 1 unita' = 1,25 pixel, cosi' i testi hanno
la stessa dimensione fisica delle prime bozze a 800x480 e lo schermo e'
largo W = 819,2 unita' (1024 / 1,25) e alto 480.
"""
import os, sys, math, random
from PIL import Image, ImageDraw, ImageFont

HERE = os.path.dirname(os.path.abspath(__file__))
FONTS = os.path.join(HERE, 'fonts')
FA = os.path.join(HERE, '..', '..', 'static', 'font', 'FA-Free-Solid.otf')
PX_W, PX_H = 1024, 600          # risoluzione del display
DS = 1.25                        # pixel per unita' di progetto
W, H = PX_W / DS, PX_H / DS      # 819.2 x 480 unita'
SS = 3                           # sovracampionamento per bordi puliti
S = DS * SS

BG=(12,14,15); CARD=(24,27,29); LINE=(44,48,51); GRID=(32,36,38)
TEXT=(244,241,236); MUTED=(135,141,146); EMBER=(255,110,30); OK=(88,200,120)
P1=(120,190,255); P2=(200,160,255)

def font(name, px):
    return ImageFont.truetype(name if name.startswith('/') else os.path.join(FONTS, name), int(px*S))
F_BIG=lambda px: font('BarlowCondensed-SemiBold.ttf', px)
F_MED=lambda px: font('BarlowCondensed-Medium.ttf', px)
F_UI=lambda px: font('Barlow-SemiBold.ttf', px)
F_UIR=lambda px: font('Barlow-Medium.ttf', px)
F_ICON=lambda px: font(FA, px)
I = lambda code: chr(code)

class Canvas:
    def __init__(self):
        self.im=Image.new('RGB',(PX_W*SS,PX_H*SS),BG); self.d=ImageDraw.Draw(self.im)
    def s(self,*v): return [x*S for x in v]
    def rrect(self,x0,y0,x1,y1,r,fill=None,outline=None,width=1):
        self.d.rounded_rectangle(self.s(x0,y0,x1,y1),radius=r*S,fill=fill,outline=outline,width=int(width*S))
    def text(self,x,y,t,f,fill,anchor='la'): self.d.text((x*S,y*S),t,font=f,fill=fill,anchor=anchor)
    def tw(self,t,f): return self.d.textlength(t,font=f)/S
    def line(self,pts,fill,width=1): self.d.line([(x*S,y*S) for x,y in pts],fill=fill,width=int(width*S),joint='curve')
    def circle(self,cx,cy,r,fill): self.d.ellipse(self.s(cx-r,cy-r,cx+r,cy+r),fill=fill)
    def done(self): return self.im.resize((PX_W,PX_H),Image.LANCZOS)

def series():
    random.seed(7); n=90  # 90 minuti, un punto al minuto
    grill=[]; p1=[]; p2=[]
    for m in range(n):
        g = 22+88*(1-math.exp(-m/9)) + (random.uniform(-2.5,2.5) if m>20 else 0)
        grill.append(g)
        p1.append(8+63*(1-math.exp(-m/70))/(1-math.exp(-(n-1)/70)))
        p2.append(8+66*(1-math.exp(-m/38))/(1-math.exp(-(n-1)/38)))
    grill[-1]=112
    return grill,p1,p2

def status_bar(c):
    c.circle(26,30,6,EMBER)
    c.text(42,30,'MANTENIMENTO',F_UI(20),TEXT,'lm')
    c.text(W/2-14,30,I(0xf017),F_ICON(17),MUTED,'mm')
    c.text(W/2,30,'2:14',F_MED(26),TEXT,'lm')
    x=W-24
    for code,on,isnet in ((0xf1eb,True,True),(0xf46a,False,False),(0xf101,True,False),(0xf863,True,False)):
        col = TEXT if isnet else (EMBER if on else LINE)
        c.text(x,30,I(code),F_ICON(18),col,'rm'); x-=40
    c.text(x-6,30,'18:47',F_MED(22),MUTED,'rm')
    c.line([(0,58),(W,58)],LINE,1)

def grill_block(c):
    c.text(28,76,'GRILL',F_UI(17),MUTED,'la')
    f=F_BIG(150); c.text(20,236,'112',f,TEXT,'ls')
    c.text(28+c.tw('112',f),108,'°C',F_MED(32),MUTED,'la')
    c.rrect(28,252,330,258,3,fill=LINE); c.rrect(28,252,330,258,3,fill=EMBER)
    # target + smoke+
    c.rrect(28,272,176,300,14,fill=CARD)
    c.text(44,286,'TARGET',F_UI(13),MUTED,'lm')
    c.text(160,286,'110°',F_BIG(26),EMBER,'rm')
    c.rrect(186,272,330,300,14,outline=LINE,width=1.5)
    c.text(204,286,I(0xf0c2),F_ICON(14),TEXT,'lm')
    c.text(228,286,'Smoke+ attivo',F_UIR(15),TEXT,'lm')

def graph(c, grill, p1, p2):
    x0,y0,x1,y1=352,72,W-24,300
    c.rrect(x0,y0,x1,y1,16,fill=CARD)
    c.text(x0+18,y0+20,'ULTIMI 90 MINUTI',F_UI(13),MUTED,'lm')
    # legenda
    lx=x1-18
    for name,col in (('Petto',P2),('Spalla',P1),('Grill',EMBER)):
        c.text(lx,y0+20,name,F_UIR(13),TEXT,'rm'); lx-=c.tw(name,F_UIR(13))+8
        c.circle(lx,y0+20,4,col); lx-=18
    gx0,gy0,gx1,gy1=x0+44,y0+44,x1-18,y1-30
    vmax=150
    ty=lambda v: gy1-(v/vmax)*(gy1-gy0)
    for v in (0,50,100,150):
        c.line([(gx0,ty(v)),(gx1,ty(v))],GRID,1)
        c.text(gx0-8,ty(v),f'{v}°',F_MED(13),MUTED,'rm')
    n=len(grill); tx=lambda i: gx0+i*(gx1-gx0)/(n-1)
    for i,lab in ((0,'-90′'),(30,'-60′'),(60,'-30′'),(n-1,'ora')):
        c.text(tx(i),gy1+16,lab,F_MED(13),MUTED,'mm')
    # setpoint tratteggiato
    sx=gx0
    while sx<gx1:
        c.line([(sx,ty(110)),(min(sx+6,gx1),ty(110))],(150,70,25),1)
        sx+=12
    for data,col,w in ((p2,P2,2),(p1,P1,2),(grill,EMBER,2.6)):
        c.line([(tx(i),ty(v)) for i,v in enumerate(data)],col,w)
    c.circle(tx(n-1),ty(grill[-1]),5,EMBER)

CARD_W=(W-48-2*19)/3   # tre schede in basso, 19 unita' di spazio tra l'una e l'altra
def card_x(i): return 24+i*(CARD_W+19)

def probe(c,x0,name,temp,target,col):
    x1,y0,y1=x0+CARD_W,318,456
    c.rrect(x0,y0,x1,y1,16,fill=CARD)
    c.circle(x0+24,y0+26,5,col)
    c.text(x0+36,y0+26,name.upper(),F_UI(15),MUTED,'lm')
    reached=temp>=target
    c.text(x0+20,y0+102,f'{temp}°',F_BIG(72),OK if reached else TEXT,'ls')
    tt=f'{target}°'
    c.text(x1-20,y0+96,tt,F_MED(26),MUTED,'rs')
    c.text(x1-26-c.tw(tt,F_MED(26)),y0+86,I(0xf140),F_ICON(14),MUTED,'rm')
    frac=max(0,min(1,temp/target))
    c.rrect(x0+20,y1-22,x1-20,y1-16,3,fill=LINE)
    c.rrect(x0+20,y1-22,x0+20+(x1-x0-40)*frac,y1-16,3,fill=OK if reached else EMBER)
    if reached:
        c.text(x1-20,y0+26,'PRONTO',F_UI(13),OK,'rm')

def timer_card(c,x0):
    x1,y0,y1=x0+CARD_W,318,456
    c.rrect(x0,y0,x1,y1,16,fill=CARD)
    c.text(x0+20,y0+26,I(0xf2f2),F_ICON(15),MUTED,'lm')
    c.text(x0+42,y0+26,'TIMER',F_UI(15),MUTED,'lm')
    c.text(x0+20,y0+102,'45:00',F_BIG(72),TEXT,'ls')
    c.text(x0+20,y1-20,'Spruzzare le costine',F_UIR(15),MUTED,'lm')

def screen_home():
    c=Canvas(); g,p1,p2=series()
    status_bar(c); grill_block(c); graph(c,g,p1,p2)
    probe(c,card_x(0),'Spalla',71,93,P1); probe(c,card_x(1),'Petto',74,74,P2); timer_card(c,card_x(2))
    return c.done()

def screen_setpoint(value=110,vmin=50,vmax=260):
    c=Canvas()
    c.text(28,30,I(0xf060),F_ICON(18),MUTED,'lm'); c.text(58,30,'Temperatura grill',F_UI(20),TEXT,'lm')
    c.line([(0,58),(W,58)],LINE,1)
    cx,cy,r=(W-200)/2,272,160; a0=135; box=(cx-r,cy-r,cx+r,cy+r)
    c.d.arc(c.s(*box),a0,a0+270,fill=LINE,width=int(18*S))
    frac=(value-vmin)/(vmax-vmin)
    c.d.arc(c.s(*box),a0,a0+270*frac,fill=EMBER,width=int(18*S))
    ang=math.radians(a0+270*frac); c.circle(cx+r*math.cos(ang),cy+r*math.sin(ang),15,TEXT)
    c.text(cx,cy+30,str(value),F_BIG(150),TEXT,'ms'); c.text(cx,cy+64,'°C',F_MED(32),MUTED,'mm')
    c.text(cx-r+4,cy+r-34,f'{vmin}°',F_MED(22),MUTED,'mm'); c.text(cx+r-4,cy+r-34,f'{vmax}°',F_MED(22),MUTED,'mm')
    # preset rapidi sulla destra
    px0,px1=W-24-170,W-24
    c.text(px0+10,120,'PRESET',F_UI(13),MUTED,'la')
    for i,(lab,v) in enumerate((('Affumicatura',90),('Low & slow',110),('Arrosto',180),('Rosolatura',230))):
        y=144+i*58; on=(v==value)
        c.rrect(px0,y,px1,y+46,12,fill=CARD if on else None,outline=None if on else LINE,width=1.5)
        c.text(px0+16,y+23,lab,F_UI(15) if on else F_UIR(15),TEXT if on else MUTED,'lm')
        c.text(px1-14,y+23,f'{v}°',F_MED(20),EMBER if on else MUTED,'rm')
    c.text(W/2,462,'Ruota la manopola o tocca un preset  ·  Premi per confermare',F_UIR(15),MUTED,'mm')
    return c.done()

def screen_wifi():
    """Rete di emergenza (wifi/manager.py): cosa mostra il display quando il grill non trova il Wi-Fi."""
    import qrcode
    c=Canvas()
    c.circle(26,30,6,EMBER); c.text(42,30,'RETE DI EMERGENZA',F_UI(20),TEXT,'lm')
    c.text(W-24,30,I(0xf1eb),F_ICON(18),EMBER,'rm')
    c.line([(0,58),(W,58)],LINE,1)
    c.text(28,92,'Il grill non trova il Wi-Fi',F_BIG(40),TEXT,'lm')
    c.text(28,128,'Scegli la rete nuova dal telefono, in due passi:',F_UIR(17),MUTED,'lm')
    steps=(('1','Collegati alla rete','PiFire-Setup','senza password'),
           ('2','Apri nel browser','http://10.42.0.1','si apre anche da sola'))
    for i,(n,lab,big,note) in enumerate(steps):
        y0=156+i*118; x1=W-24-262
        c.rrect(24,y0,x1,y0+102,16,fill=CARD)
        c.circle(62,y0+51,22,EMBER); c.text(62,y0+51,n,F_BIG(30),(26,14,6),'mm')
        c.text(100,y0+30,lab.upper(),F_UI(14),MUTED,'lm')
        c.text(100,y0+66,big,F_BIG(38),TEXT,'lm')
        c.text(x1-18,y0+30,note,F_UIR(14),MUTED,'rm')
    c.text(28,416,'Da questa rete si sceglie solo il Wi-Fi: il grill non si comanda.',F_UIR(15),MUTED,'lm')
    c.text(28,444,'Quando il grill torna in rete, qui compare il suo indirizzo.',F_UIR(15),MUTED,'lm')
    # QR per collegarsi alla rete aperta
    qx0,qy0,qx1=W-24-244,156,W-24
    c.rrect(qx0,qy0,qx1,qy0+220,16,fill=CARD)
    qr=qrcode.QRCode(border=2,box_size=10); qr.add_data('WIFI:T:nopass;S:PiFire-Setup;;'); qr.make(fit=True)
    img=qr.make_image(fill_color=(12,14,15),back_color=(244,241,236)).convert('RGB')
    side=168; img=img.resize((int(side*S),int(side*S)),Image.NEAREST)
    c.im.paste(img,(int((qx0+(qx1-qx0-side)/2)*S),int((qy0+16)*S)))
    c.text((qx0+qx1)/2,qy0+204,'Inquadra per collegarti',F_UIR(14),MUTED,'mm')
    return c.done()

if __name__=='__main__':
    out=sys.argv[1] if len(sys.argv)>1 else HERE
    screen_home().save(os.path.join(out,'5in_home.png'))
    screen_setpoint().save(os.path.join(out,'5in_setpoint.png'))
    screen_wifi().save(os.path.join(out,'5in_wifi.png'))
    print('ok')
