import subprocess

def sample(path, pages):
    for p in pages:
        t=subprocess.check_output(["pdftotext","-f",str(p),"-l",str(p),"-layout",path,"-"], text=True, errors="replace")
        lines=t.splitlines()
        al=sum(c.isalnum() for c in t)
        print(f"--- PDF {p} alnum={al} ---")
        print("\n".join(lines[:10])[:450])
        print()

print("==== MV I ====")
sample("/data/pdf/vdoc.pub_multiplicative-number-theory-i-classical-theory.pdf", [10,11,12,13,14,15,16, 520,530,540,550,560,571])
print("==== MV II ====")
sample("/data/pdf/montgomery-vaughanIIMultiplicative number theory.pdf", [8,9,10,11,12,13,14, 440,448,450,454,458,472])
print("==== BURDE ====")
sample("/data/pdf/burde_81_annt_courseAnalytic Number Theory.pdf", [3,4,5,6,7,110,114,115,118])
print("==== WUSTHOLZ ====")
sample("/data/pdf/406208375-A-panorama-in-number-theory-G-Wustholz-pdf.pdf", [10,11,12,13,14,15,16, 360,370,374])
print("==== RAM3 ====")
sample("/data/pdf/RamanujanNotebooksPart3Berndt.pdf", [10,11,12,13,14,15, 500,505,510,521])
print("==== RAM4 ====")
sample("/data/pdf/Ramanujan Notebooks4Berndt.pdf", [8,9,10,11,12,15,20, 210,220,225,231])
print("==== CAI ====")
sample("/data/pdf/953736487-经典数论的现代导引-蔡天新-著-Z-Library.pdf", [12,13,14,15,16,17,18,19,20, 280,285,290,293])
