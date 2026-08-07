import subprocess

def show(path,pages):
  for p in pages:
    t=subprocess.check_output(["pdftotext","-f",str(p),"-l",str(p),"-layout",path,"-"], text=True, errors="replace")
    print(f"PDF{p}:", " | ".join(t.splitlines()[:6])[:200])

show("/data/pdf/vdoc.pub_multiplicative-number-theory-i-classical-theory.pdf", [504,505,506,550,555,560,565,568,571])
show("/data/pdf/Ramanujan Notebooks4Berndt.pdf", [7,8,9])
show("/data/pdf/TomIntroduction to Analytic Number Theory.pdf", [343,344,345,346,347])
show("/data/pdf/burde_81_annt_courseAnalytic Number Theory.pdf", [3,4])
show("/data/pdf/421432598-METHODS-OF-SOLVING-NUMBER-THEORIES.pdf", [50,100])  # headers
show("/data/pdf/437419531-Number-theory-and-geometry.pdf", [50,100])
