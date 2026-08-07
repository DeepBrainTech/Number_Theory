import subprocess

def sample(path, pages):
    for p in pages:
        t=subprocess.check_output(["pdftotext","-f",str(p),"-l",str(p),"-layout",path,"-"], text=True, errors="replace")
        lines=t.splitlines()
        al=sum(c.isalnum() for c in t)
        print(f"--- PDF {p} alnum={al} ---")
        print("\n".join(lines[:12])[:500])
        print()

# Grigorieva: TOC printed p1 = ch1; contents PDF ~18-19; ch1 after contents
sample("/data/pdf/421432598-METHODS-OF-SOLVING-NUMBER-THEORIES.pdf", [20,21,22, 350,360,370,377,380,389,400])
print("==== LOZANO ====")
sample("/data/pdf/437419531-Number-theory-and-geometry.pdf", [14,15,16,17,18, 470,475,479,483,490,500])
print("==== APOSTOL ====")
sample("/data/pdf/TomIntroduction to Analytic Number Theory.pdf", [7,8,9,10,11,12,13,14, 330,335,340,345,350])
print("==== TENENBAUM ====")
sample("/data/pdf/489076707-Introduction-to-Analytic-and-Probabilistic-Number-Theory.pdf", [14,15,16,17,18,19,20, 440,450,455,460,466])
