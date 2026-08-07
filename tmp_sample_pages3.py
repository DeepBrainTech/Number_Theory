import subprocess

def head(path,p,n=15):
    t=subprocess.check_output(["pdftotext","-f",str(p),"-l",str(p),"-layout",path,"-"], text=True, errors="replace")
    al=sum(c.isalnum() for c in t)
    print(f"PDF{p} al={al}")
    print("\n".join(t.splitlines()[:n])[:600])
    print("---")

print("CAI ch1/refs")
for p in range(21,26):
    head("/data/pdf/953736487-经典数论的现代导引-蔡天新-著-Z-Library.pdf",p,8)
head("/data/pdf/953736487-经典数论的现代导引-蔡天新-著-Z-Library.pdf",286,8)

print("MVI ch1/app")
for p in [17,18,19,20]:
    head("/data/pdf/vdoc.pub_multiplicative-number-theory-i-classical-theory.pdf",p,8)
head("/data/pdf/vdoc.pub_multiplicative-number-theory-i-classical-theory.pdf",503,8)
head("/data/pdf/vdoc.pub_multiplicative-number-theory-i-classical-theory.pdf",545,8)

print("BURDE")
for p in [5,6,7,112,113,114,115,116]:
    head("/data/pdf/burde_81_annt_courseAnalytic Number Theory.pdf",p,6)

print("WUSTHOLZ ch1")
for p in [14,15,16,17]:
    head("/data/pdf/406208375-A-panorama-in-number-theory-G-Wustholz-pdf.pdf",p,8)

print("RAM3")
for p in [14,15,16,17]:
    head("/data/pdf/RamanujanNotebooksPart3Berndt.pdf",p,8)
head("/data/pdf/RamanujanNotebooksPart3Berndt.pdf",505,6)
head("/data/pdf/RamanujanNotebooksPart3Berndt.pdf",512,6)

print("APOSTOL bib")
for p in [336,337,338,339,340,341,342]:
    head("/data/pdf/TomIntroduction to Analytic Number Theory.pdf",p,6)

print("LOZANO dens")
for p in [100,200,250,252,253,254,300]:
    t=subprocess.check_output(["pdftotext","-f",str(p),"-l",str(p),"/data/pdf/437419531-Number-theory-and-geometry.pdf","-"], text=True, errors="replace")
    print(f"lozano p{p} al={sum(c.isalnum() for c in t)}")
