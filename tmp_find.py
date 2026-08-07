import subprocess

def find_first(path, start, end, needle):
    for p in range(start,end+1):
        t=subprocess.check_output(["pdftotext","-f",str(p),"-l",str(p),path,"-"], text=True, errors="replace")
        if needle.lower() in t[:1200].lower():
            print(f"{path.split('/')[-1][:40]} PDF{p}: {needle} | {t.splitlines()[0][:80] if t.splitlines() else ''}")
            return p
    print(f"NOT FOUND {needle} in {start}-{end}")
    return None

find_first("/data/pdf/burde_81_annt_courseAnalytic Number Theory.pdf", 110, 118, "Bibliography")
find_first("/data/pdf/406208375-A-panorama-in-number-theory-G-Wustholz-pdf.pdf", 18, 28, "One Century of Logarithmic")
find_first("/data/pdf/RamanujanNotebooksPart3Berndt.pdf", 18, 35, "q-Series and Theta")
find_first("/data/pdf/RamanujanNotebooksPart3Berndt.pdf", 500, 521, "Index")
find_first("/data/pdf/vdoc.pub_multiplicative-number-theory-i-classical-theory.pdf", 500, 520, "APPENDICES")
find_first("/data/pdf/vdoc.pub_multiplicative-number-theory-i-classical-theory.pdf", 500, 520, "The Riemann")
find_first("/data/pdf/vdoc.pub_multiplicative-number-theory-i-classical-theory.pdf", 545, 571, "Author index")
find_first("/data/pdf/437419531-Number-theory-and-geometry.pdf", 490, 506, "Bibliography")
find_first("/data/pdf/421432598-METHODS-OF-SOLVING-NUMBER-THEORIES.pdf", 350, 360, "Chapter 5")
find_first("/data/pdf/421432598-METHODS-OF-SOLVING-NUMBER-THEORIES.pdf", 390, 404, "References")
find_first("/data/pdf/montgomery-vaughanIIMultiplicative number theory.pdf", 340, 355, "Appendix E")
find_first("/data/pdf/montgomery-vaughanIIMultiplicative number theory.pdf", 455, 472, "Errata")
find_first("/data/pdf/TomIntroduction to Analytic Number Theory.pdf", 343, 350, "Index")
find_first("/data/pdf/Ramanujan Notebooks4Berndt.pdf", 1, 12, "CHAPTER 22")
