"""Knuth-Liang pattern-based hyphenation.

The algorithm (Liang, 1983) scores every inter-letter position in a word
by matching a set of patterns; odd scores permit a break, even scores
forbid one. Full TeX pattern sets run to ~4500 entries per language --
this module ships a reduced English set sufficient for correct behaviour
on common text, and loads full sets from data files when present.

Pattern files are in TeX `hyph-*.tex` format (public domain / LPPL).
Point `HyphenationDictionary.load()` at a directory of them to get
production-grade coverage.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

__all__ = ["Hyphenator", "NO_BREAK_TERMS"]

# A reduced English pattern set. Each pattern encodes digits between
# letters; '.' anchors to a word boundary.
_EN_PATTERNS = """
.ach4 .ad4der .af1t .al3t .am5at .an5c .ang4 .ani5m .ant4 .an3te .anti5s
.ar5s .ar4tie .ar4ty .as3c .as1p .as1s .aster5 .atom5 .au1d .av4i .awn4
.ba4g .ba5na .bas4e .ber4 .be5ra .be3sm .be5sto .bri2 .but4ti .cam4pe
.can5c .capa5b .car5ol .ca4t .ce4la .ch4 .chill5i .ci2 .cit5r .co3e
.co4r .cor5ner .de4moi .de3o .de3ra .de3ri .des4c .dictio5 .do4t .du4c
.dumb5 .earth5 .eas3i .eb4 .eer4 .eg2 .el5d .el3em .enam3 .en3g .en3s
.eq5ui5t .er4ri .es3 .eu3 .eye5 .fes3 .for5mer .ga2 .ge2 .gen3t4 .ge5og
.gi5a .gi4b .go4r .hand5i .han5k .he2 .hero5i .hes3 .het3 .hi3b .hi3er
.hon5ey .hon3o .hov5 .id4l .idol3 .im3m .im5pin .in1 .in3ci .ine2 .in2k
.in3s .ir5r .is4i .ju3r .la4cy .la4m .lat5er .lath5 .le2 .leg5e .len4
.lep5 .lev1 .li4g .lig5a .li2n .li3o .li4t .mag5a5 .mal5o .man5a .mar5ti
.me2 .mer3c .me5ter .mis1 .mist5i .mon3e .mo3ro .mu5ta .muta5b .ni4c
.od2 .odd5 .of5te .or5ato .or3c .or1d .or3t .os3 .os4tl .oth3 .out3
.ped5al .pe5te .pe5tit .pi4e .pio5n .pi2t .pre3m .ra4c .ran4t .ratio5na
.ree2 .re5mit .res2 .re5stat .ri4g .rit5u .ro4q .ros5t .row5d .ru4d
.sci3e .self5 .sell5 .se2n .se5rie .sh2 .si2 .sing4 .st4 .strat5
.sur3f .swi2 .tea5m .tel2 .te2n .ter4b .te3to .thin4 .tho3se .three5
.ti2 .til4 .tim5o5 .ting4 .tin5k .ton4a .to4p .top5i .tou5s .trib5ut
.un1a .un3ce .under5 .un1e .un5k .un5o .un3u .up3 .ure3 .us5a .ut3l
.ver4dic4 .vi4l .vi4z .wil2 .ye4 4ab. a5bal a5ban abe2 ab5erd abi5a
ab5it5ab ab5lat ab5o5liz 4abr ab5rog ab3ul a4car ac5ard ac5aro a5ceou
ac1er a5chet 4a2ci a3cie ac1in a3cio ac5rob act5if ac3ul ac4um a2d
ad4din ad5er. 2adi a3dia ad3ica adi4er a3dio a3dit a5diu ad4le ad3ow
ad5ran ad4su 4adu a3duc ad5um ae4r aeri4e a2f aff4 a4gab aga4n ag5ell
age4o 4ageu ag1i 4ag4l ag1n a2go 3agog ag3oni a5guer ag5ul a4gy a3ha
a3he ah4l a3ho ai2 a5ia a3ic. ai5ly a4i4n ain5in ain5o ait5en a1j
ak1en al5ab al3ad a4lar 4aldi 2ale al3end a4lenti a5le5o al1i al4ia.
ali4e al5lev 4allic 4alm a5log. a4ly. 4alys 5a5lyst 5alyt 3alyz 4ama
am5ab am3ag ama5ra am5asc a4matis a4m5ato am5era am3ic am5if am5ily
am1in ami4no a2mo a5mon amor5i amp5en a2n an3age 3analy a3nar an3arc
anar4i a3nati 4and ande4s an3dis an1dl an4dow a5nee a3nen an5est.
a3neu 2ang ang5ie an1gl a4n1ic a3nies an3i3f an4ime a5nimi a5nine
an3io a3nip an3ish an3it a3niu an4kli 5anniz ano4 an5ot anoth5 an2sa
an4sco an4sn an2sp ans3po an4st an4sur antal4 an4tie 4anto an2tr an4tw
an3ua an3ul a5nur 4ao apar4 ap5at ap5ero a3pher 4aphi a4pilla ap5illar
ap3in ap3ita a3pitu a2pl apoc5 ap5ola apor5i apos3t aps5es a3pu aque5
2a2r ar3act a5rade ar5adis ar3al a5ramete aran4g ara3p ar4at a5ratio
ar5ativ a5rau ar5av4 araw4 arbal4 ar4chan ar5dine ar4dr ar5eas a3ree
ar3ent a5ress ar4fi ar4fl ar1i ar5ial ar3ian a3riet ar4im ar5inat
ar3io ar2iz ar2mi ar5o5d a5roni a3roo ar2p ar3q arre4 ar4sa ar2sh
4as. as4ab as3ant ashi4 a5sia. a3sib a3sic 5a5si4t ask3i as4l a4soc
as5ph as4sh as3ten as1tr asur5a a2ta at3abl at5ac at3alo at5ap ate5c
at5ech at3ego at3en. at3era ater5n a5terna at3est at5ev 4ath ath5em
a5then at4ho ath5om 4ati. a5tia at5i5b at1ic at3if ation5ar at3itu
a4tog a2tom at5omiz a4top a4tos a1tr at5rop at4sk at4tag at5te at4th
a2tu at5ua at5ue at3ul at3ura a2ty au4b augh3 au3gu au4l2 aun5d au3r
au5sib aut5en au1th a2va av3ag a5van ave4no av3era av5ern av5ery av1i
avi4er av3ig av5oc a1vor 3away aw3i aw4ly aws4 ax4ic ax4id ay5al aye4
ays4 azi4er azz5i 5ba. bad5ger ba4ge bal1a ban5dag ban4e ban3i barbi5
bari4a bas4si 1bat ba4z 2b1b b2be b3ber bbi4na 4b1d 4be. beak4 beat3
4be2d be3da be3de be3di be3gi be5gu 1bel be1li be3lo 4be5m be5nig
be5nu 4bes4 be3sp be5str 3bet bet5iz be5tr be3tw be3w be5yo 2bf 4b3h
bi2b bi4d 3bie bi5en bi4er 2b3if 1bil bi3liz bina5r4 bin4d bi5net
bi3ogr bi5ou bi2t 3bi3tio bi3tr 3bit5ua b5itz b1j bk4 b2l2 blath5
b4le. blen4 5blesp b3lis b4lo blun4t 4b1m 4b3n bne5g 3bod bod3i bo4e
bol3ic bom4bi bon4a bon5at 3boo 5bor. 4b1ora bor5d 5bore 5bori 5bos4
b5ota both5 bo4to bound3 4bp 4brit broth3 2b5s2 bsor4 2bt bt4l b4to
b3tr buf4fer bu4ga bu3li bumi4 bu4n bunt4i bu3re bus5ie buss4e 5bust
4buta 3butio b5uto b1v 4b5w 5by. bys4 1ca cab3in ca1bl cach4 ca5den
4cag4 2c5ah ca3lat cal4la call5in 4calo can5d can4e can4ic can5is
can3iz can4ty cany4 ca5per car5om cast5er cas5tig 4casy ca4th 4cativ
cav5al c3c ccha5 cci4a ccompa5 ccon4 ccou3t 2ce. 4ced. 4ceden 3cei
5cel. 3cell 1cen 3cenc 2cen4e 4ceni 3cent 3cep ce5ram 4cesa 3cessi
ces5si5b ces5t cet4 c5e4ta cew4 2ch 4ch. 4ch3ab 5chanic ch5a5nis
che2 cheap3 4ched che5lo 3chemi ch5ene ch3er. ch3ers 4ch1in 5chine.
ch5iness 5chini 5chio 3chit chi2z 3cho2 ch4ti 1ci 3cia ci2a5b cia5r
ci5c 4cier 5cifi c4if4y 4cim 4cin c4ina 3cinat cin3em c1ing c5ing.
5cino cion4 4cipe ci3ph 4cipic 4cista 4cisti 2c1it cit3iz 5ciz ck1
ck3i 1c4l4 4clar c5laratio 5clare cle4m 4clic clim4 cly4 c5n 1co
co5ag coe2 2cog co4gr coi4 co3inc col5i 5colo col3or com5er con4a
c4one con3g con5t co3pa cop3ic co4pl 4corb coro3n cos4e cov1 cove4
cow5a coz5e co5zi c1q cras5t 5crat. 5cratic cre3at 5cred 4c3reta
cre4v cri2 cri5f c4rin cris4 5criti cro4pl crop5o cros4e cru4d 4c3s2
2c1t cta4b ct5ang c5tant c2te c3ter c4ticu ctim3i ctu4r c4tw cud5
c4uf c4ui cu5ity 5culi cul4tis 3cultu cu2ma c3ume cu4mi 3cun cu3pi
cu5py cur5a4b cu5ria 1cus cus3s4 3cut cu4tie 4c5utiv 4cutr 1cy cze4
1d2a 5da. 2d3a4b dach4 4daf 2dag da2m2 dan3g dard5 dark5 4dary 3dat
4dativ 4dato 5dav4 dav5e 5day d3c d1d4 2de. deaf5 deb5it de4bon
decan4 de4cil de5com 2d1ed 4dee. de5if deli4e del5i5q de5lo d4em
5dem. 3demic dem5ic. de5mil de4mons demor5 1den de4nar de3no denti5f
de3nu de1p de3pa depi4 de2pu d3eq d4erh 5derm dern5iz der5s des2
d2es. de1sc de2s5o des3ti de3str de4su de1t de2to de1v dev3il 4dey
4d1f d4ga d3ge4t dg1i d2gy d1h2 5di. 1di3a dia5b di4cam d4ice 3dict
3did 5di3en d1if di3ge di4lato d1in 1dina 3dine. 5dini di5niz 1dio
dio5g di4pl dir2 di1re dirt5i dis1 5disi d4is3t d2iti 1di1v d1j
d5k2 4d5la 3dle. 3dled 3dles. 4dless 2d3lo 4d5lu 2dly d1m 4d1n4
1do 3do. do5de 5dogm do4la doli4 do5lor dom5iz do3nat doni4 doo3d
dop4p d4or 3dos 4d5out do4v 3dox d1p 1dr drag5on 4drai dre4 drea5r
5dren dri4b dril4 dro4p 4drow 5drupli 4dry 2d1s2 ds4p d4sw d4sy
d2th 1du d1u1a du2c d1uca duc5er 4duct. 4ducts du5el du4g d3ule
dum4be du4n 4dup du4pe d1v d1w d2y 5dyn dy4se dys5p e1a4b e3act
ead1 ead5ie ea4ge ea5ger ea4l eal5er eal3ou eam3er e5and ear3a
ear4c ear5es ear4ic ear4il ear5k ear2t eart3e ea5sp e3ass east3
ea2t eat5en eath3i e5atif e4a3tu ea2v eav3en eav5i eav5o 2e1b
e4bel. e4bels e4ben e4bit e3br e4cad ecan5c ecca5 e1ce ec5essa
ec2i e4cib ec5ificat ec5ifie ec5ify ec3im e4cite e5clam e4clus
e2col e4comm e4compe e4conc e2cor ec3ora eco5ro e1cr e4crem ec4tan
ec4te e1cu e4cul ec3ula 2e2da 4ed3d e4d1er ede4s 4edi e3dia ed3ib
ed3ica ed3im ed1it edi5z 4edo e4dol edon2 e4dri e4dul ed5ulo ee2c
eed3i ee2f eel3i ee4ly ee2m ee4na ee4p1 ee2s4 eest4 ee4ty e5ex e1f
e4f3ere 1eff e4fic 5efici efil4 e3fine ef5i5nit 3efit efor5es e4fuse.
4egal eger4 eg5ib eg4ic eg5ing e5git5 eg5n e4go. e4gos eg1ul e5gur
5egy e1h4 eher4 ei2 e5ic ei5d eig2 ei5gl e3imb e3inf e1ing e5inst
eir4d eit3e ei3th e5ity e1j e4jud ej5udi eki4n ek4la e1la e4la.
e4lac elan4d el5ativ e4law elaxa4 e3lea el5ebra 5elec e4led el3ega
e5len e4l1er e1les el2f el2i e3libe e4lic. el3ica e3lier el5igib
e5lim e4l3ing e3lio e2lis el5ish e3liv3 4ella el4lab ello4 e5loc
el5og el3op. el2sh el4ta e5lud el5ug e4mac e4mag e5man em5ana
em5b e1me e2mel e4met em3ica emi4e em5igra em1in2 em5ine em3i3ni
e4mis em5ish e5miss em3iz 5emniz emo4g emoni5o em3pi e4mul em5ula
emu3n e3my en5amo e4nant ench4er en3dic e5nea e5nee en3em en5ero
en5esi en5est en3etr e3new en5ics e5nie e5nil e3nio en3ish en3it
e5niu 5eniz 4enn 4eno eno4g e4nos en3ov en4sw ent5age 4enthes
en3ua en5uf e3ny. 4en3z e5of eo2g e4oi4 e3ol eop3ar e1or eo3re
eo5rol eos4 e4ot eo4to e5out e5ow e2pa e3pai ep5anc e5pel e3pent
ep5etitio ephe4 e4pli e1po e4prec ep5reca e4pred ep3reh e3pro
e4prob ep4sh ep5ti5b e4put ep5uta e1q equi3l e4q3ui3s er1a era4b
4erand er3ar 4erati. 2erb er4bl er3ch er4che 2ere. e3real ere5co
ere3in er5el. er3emo er5ena er5ence 4erene er3ent ere4q er5ess
er3est eret4 er1h er1i e1ria4 5erick e3rien eri4er er3ine e1rio
4erit er4iu eri4v e4riva er3m4 er4nis 4ernit 5erniz er3no 4ero4g
er5ou er1p er3r4 5erra er3set ert3er 4ertl er3tw 4eru eru4t 5erwau
e1s4a e4sage. e4sages es2c e2sca es5can e3scr es5cu e1s2e e2sec
es5ecr es5enc e4sert. e4serts e4serva 4esh e3sha esh5en e1si e2sic
e2sid es5iden es5igna e2s5im es4i4n esis4te esi4u e5skin ep5ti5b
e4put ep5uta e1q equi3l e4q3ui3s
""".split() + """
hy3ph he2n hena4 h4y2 y1p2h 2ph 1na4 na4t 1ti2o ti4on a2t2i 4tion. 3ation.
5ations. 1a2tion 2ta4ble 4able. 4ably. 4ance. 4ancy. 4ence. 4ency. 4ent.
4ment. 5ments. 4ness. 4less. 4ful. 4fully. 4ship. 4hood. 4ward. 4wise.
3ing. 4ings. 3ize 3izes 3ized 3izing 3ism 3ist 3istic 4ity. 5ities. 4ive.
4ively. 4ous. 4ously. 4sion. 5sions. 4tive. 4ture. 5tures. 4sure. 4cial.
4tial. 4cian. 4tian. 4ical. 4icle. 4ible. 4ibly. 2i3ty 2al1i 4ally. 3ical
in1ter in3tro dis1 mis1 non1 pre3 pro3 re1 sub3 super3 trans3 un1 over1
under1 anti3 auto3 co3 de3 semi3 multi3 counter3 4ledge 3ment 2m1ent
com4pu 5puter 4graph 3graphy 4logi 5logic 3logy 3nomic 3nomy 4meter 3metry
4scope 4scopy 4pathy 4phobia 4gram 4graphi 2s1hip 4board 4room 4work
per1 per4son 5sonal 4sonn 5sonnel 4tribu 5bution 3lease 4lease. 4leases.
3sent 4sente 5sentat 4sider 5sidera 4stance 5stances 4strat 5stration
4tract 5tractu 4vision 4visio 5visions 4quire 5quirem 4vestig 5vestiga
4propri 5propriat 4pportun 4bilit 5bilities 4mplement 5mentation
4nalys 5nalysis 4sess 5sessment 4valu 5valuati 4curit 5curity
""".split()

#: Terms that must never be hyphenated in legal or financial text.
#: Breaking these across lines changes how a reader parses them.
NO_BREAK_TERMS = frozenset({
    "inc", "corp", "llc", "llp", "ltd", "plc", "lp", "pa", "na", "sa",
    "gmbh", "ag", "bv", "nv", "pty", "co", "usa", "us", "uk", "eu",
    "sec", "irs", "fda", "ftc", "doj", "sro", "finra", "gaap", "ifrs",
    "ebitda", "ebit", "roi", "roe", "apr", "apy", "ipo", "spac", "reit",
    "etal", "seq", "ibid", "supra", "infra", "viz", "cf", "vs",
    "plaintiff", "defendant", "appellant", "appellee",
})


def _parse_pattern(pattern: str) -> tuple:
    """Split a TeX pattern into its letters and per-position digits."""
    letters = []
    values = [0]
    for char in pattern:
        if char.isdigit():
            values[-1] = int(char)
        else:
            letters.append(char)
            values.append(0)
    return "".join(letters), tuple(values)


@dataclass
class Hyphenator:
    """Finds valid hyphenation points in words.

    `min_prefix` and `min_suffix` prevent breaks that leave a stub of one
    or two characters, which reads badly regardless of what the patterns
    permit.
    """

    language: str = "en-US"
    min_prefix: int = 2
    min_suffix: int = 3
    min_fragment: int = 2
    min_word_length: int = 5
    _patterns: dict = field(default_factory=dict, repr=False)
    _exceptions: dict = field(default_factory=dict, repr=False)
    _cache: dict = field(default_factory=dict, repr=False)

    def __post_init__(self) -> None:
        if not self._patterns:
            self._patterns = self._compile(_EN_PATTERNS)

    @staticmethod
    def _compile(patterns) -> dict:
        table = {}
        for pattern in patterns:
            letters, values = _parse_pattern(pattern)
            if letters:
                table[letters] = values
        return table

    @classmethod
    def load(cls, path: str | Path, language: str = "en-US") -> "Hyphenator":
        """Load a full TeX-format pattern file.

        Accepts either a bare newline/space separated list of patterns or
        a `\\patterns{...}` block as found in `hyph-*.tex` files.
        """
        text = Path(path).read_text(encoding="utf-8", errors="replace")
        if "\\patterns{" in text:
            start = text.index("\\patterns{") + len("\\patterns{")
            end = text.index("}", start)
            text = text[start:end]
        tokens = [
            t for t in text.split()
            if t and not t.startswith("%") and not t.startswith("\\")
        ]
        instance = cls(language=language)
        instance._patterns = cls._compile(tokens)
        return instance

    def add_exception(self, word: str, syllables) -> None:
        """Override the pattern result for one word."""
        self._exceptions[word.lower()] = list(syllables)
        self._cache.pop(word.lower(), None)

    def add_no_break(self, term: str) -> None:
        self._exceptions[term.lower()] = [term]
        self._cache.pop(term.lower(), None)

    def break_points(self, word: str) -> list:
        """Return character indices where `word` may be hyphenated."""
        key = word.lower()
        cached = self._cache.get(key)
        if cached is not None:
            return cached

        result = self._compute(word, key)
        self._cache[key] = result
        return result

    def _compute(self, word: str, key: str) -> list:
        stripped = key.strip(".,;:!?()[]\"'")
        if stripped in NO_BREAK_TERMS or stripped in self._exceptions:
            if stripped in self._exceptions:
                syllables = self._exceptions[stripped]
                if len(syllables) < 2:
                    return []
                points, position = [], 0
                for syllable in syllables[:-1]:
                    position += len(syllable)
                    points.append(position)
                return points
            return []

        if len(word) < self.min_word_length or not word.isalpha():
            return []
        # An existing hyphen is already a break opportunity; do not add more.
        if "-" in word:
            return []

        padded = "." + key + "."
        values = [0] * (len(padded) + 1)

        for i in range(len(padded)):
            for j in range(i + 1, min(i + 16, len(padded)) + 1):
                pattern_values = self._patterns.get(padded[i:j])
                if pattern_values is None:
                    continue
                for offset, value in enumerate(pattern_values):
                    index = i + offset
                    if index < len(values) and value > values[index]:
                        values[index] = value

        points = []
        # values[k] sits before padded[k]; padded has a leading '.', so a
        # value at index k corresponds to position k-1 in the real word.
        # Adjacent points must also be far enough apart, otherwise a word
        # can break into single-letter fragments that read as typos.
        last = 0
        for position in range(self.min_prefix, len(word) - self.min_suffix + 1):
            if values[position + 1] % 2 != 1:
                continue
            if position - last < self.min_fragment:
                continue
            if len(word) - position < self.min_suffix:
                continue
            points.append(position)
            last = position
        return points

    def syllables(self, word: str) -> list:
        """Split a word at its hyphenation points (useful for tests)."""
        points = self.break_points(word)
        if not points:
            return [word]
        parts, previous = [], 0
        for point in points:
            parts.append(word[previous:point])
            previous = point
        parts.append(word[previous:])
        return parts
