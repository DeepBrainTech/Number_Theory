import subprocess

def txt(path, f, l=None):
    if l is None: l=f
    return subprocess.check_output(["pdftotext","-f",str(f),"-l",str(l),"-layout",path,"-"], text=True, errors="replace")

def find(path, start, end, needles, step=1):
    hits=[]
    for p in range(start, end+1, step):
        t=txt(path,p)
        for n in needles:
            if n.lower() in t[:2000].lower():
                first=" | ".join(t.splitlines()[:8])[:180]
                hits.append((p,n,first))
                break
    return hits

checks=[
("grigorieva","/data/pdf/421432598-METHODS-OF-SOLVING-NUMBER-THEORIES.pdf", [
  (18,30,["Chapter 1","Numbers: Problems"]),
  (350,404,["Chapter 5","Homework","References","Appendix","Index"]),
]),
("lozano","/data/pdf/437419531-Number-theory-and-geometry.pdf", [
  (1,30,["Chapter 1. Introduction","Preface"]),
  (450,506,["Bibliography","Index","Chapter 15","Chapter 14"]),
]),
("apostol","/data/pdf/TomIntroduction to Analytic Number Theory.pdf", [
  (1,30,["Historical Introduction","Chapter 1","Fundamental Theorem"]),
  (320,350,["Bibliography","Suggestions for further","Index","Chapter 14"]),
]),
("tenenbaum","/data/pdf/489076707-Introduction-to-Analytic-and-Probabilistic-Number-Theory.pdf", [
  (1,40,["Preface","Some tools from real analysis","Chapter 1.0"]),
  (430,466,["Bibliography","Index","Subject index","Author index"]),
]),
("mvi","/data/pdf/vdoc.pub_multiplicative-number-theory-i-classical-theory.pdf", [
  (1,40,["Dirichlet series: I","Preface","Contents"]),
  (500,571,["APPENDICES","Author index","Subject index","Riemann"]),
]),
("mvii","/data/pdf/montgomery-vaughanIIMultiplicative number theory.pdf", [
  (1,30,["Exponential Sums I","Contents","Preface"]),
  (430,472,["Errata","Name index","Subject index","Appendix H"]),
]),
("burde","/data/pdf/burde_81_annt_courseAnalytic Number Theory.pdf", [
  (1,15,["Introduction","Chapter 1"]),
  (100,118,["Bibliography","Chapter 3"]),
]),
("wustholz","/data/pdf/406208375-A-panorama-in-number-theory-G-Wustholz-pdf.pdf", [
  (1,30,["One Century of Logarithmic","Introduction","Contents"]),
  (350,374,["Heilbronn","Schinzel","Shorey"]),
]),
("ram3","/data/pdf/RamanujanNotebooksPart3Berndt.pdf", [
  (1,30,["CHAPTER 16","q-Series","Introduction","Contents"]),
  (490,521,["References","Index","CHAPTER 21"]),
]),
("ram4","/data/pdf/Ramanujan Notebooks4Berndt.pdf", [
  (1,40,["CHAPTER 22","Elementary Results","Introduction","Contents"]),
  (200,231,["References","Index","CHAPTER 31"]),
]),
]

for name,path,ranges in checks:
  print("\n====",name,"====")
  for a,b,needles in ranges:
    hits=find(path,a,b,needles)
    for h in hits[:12]:
      print(f"  p{h[0]} [{h[1]}] {h[2]}")
    # text quality samples
  info=subprocess.check_output(["pdfinfo",path],text=True,errors="replace")
  pages=int([l for l in info.splitlines() if l.startswith("Pages:")][0].split()[1])
  for p in [pages//4, pages//2, 3*pages//4]:
    t=subprocess.check_output(["pdftotext","-f",str(p),"-l",str(p),path,"-"],text=True,errors="replace")
    al=sum(c.isalnum() for c in t)
    print(f"  density p{p}: alnum={al}")
