import subprocess, re
books = [
  ("421432598-METHODS-OF-SOLVING-NUMBER-THEORIES.pdf", [
    ("Ch1", "Numbers: Problems Involving Integers"),
    ("Homework", "Homework"),
    ("References", "References"),
    ("Index", "Index"),
  ]),
  ("437419531-Number-theory-and-geometry.pdf", [
    ("Ch1", "Chapter 1"),
    ("Bibliography", "Bibliography"),
    ("Index", "Index"),
  ]),
  ("TomIntroduction to Analytic Number Theory.pdf", [
    ("Hist", "Historical Introduction"),
    ("Ch1", "Fundamental Theorem of Arithmetic"),
    ("Bibliography", "Bibliography"),
    ("Index", "Index"),
  ]),
  ("489076707-Introduction-to-Analytic-and-Probabilistic-Number-Theory.pdf", [
    ("ChI0", "Some tools from real analysis"),
    ("Bibliography", "Bibliography"),
    ("Index", "Index"),
  ]),
  ("vdoc.pub_multiplicative-number-theory-i-classical-theory.pdf", [
    ("Ch1", "Dirichlet series: I"),
    ("AppA", "Riemann"),
    ("AuthorIndex", "Author index"),
  ]),
  ("montgomery-vaughanIIMultiplicative number theory.pdf", [
    ("Ch16", "Exponential Sums I"),
    ("Errata", "Errata for Volume 1"),
    ("NameIndex", "Name index"),
  ]),
  ("burde_81_annt_courseAnalytic Number Theory.pdf", [
    ("Intro", "Analytic number theory is a branch"),
    ("Bib", "Bibliography"),
  ]),
  ("406208375-A-panorama-in-number-theory-G-Wustholz-pdf.pdf", [
    ("Ch1", "One Century of Logarithmic Forms"),
    ("Last", "Heilbronn"),
  ]),
  ("RamanujanNotebooksPart3Berndt.pdf", [
    ("Ch16", "q-Series and Theta-Functions"),
    ("References", "References"),
    ("Index", "Index"),
  ]),
  ("Ramanujan Notebooks4Berndt.pdf", [
    ("Ch22", "Elementary Results"),
    ("References", "References"),
    ("Index", "Index"),
  ]),
]
base="/data/pdf"
for fname, needles in books:
  path=f"{base}/{fname}"
  info=subprocess.check_output(["pdfinfo", path], text=True, errors="replace")
  pages=int(re.search(r"Pages:\s+(\d+)", info).group(1))
  print(f"\n===== {fname} pages={pages} =====")
  search_pages = list(range(1, min(pages, 50)+1)) + list(range(max(1, pages-50), pages+1))
  found={}
  for p in search_pages:
    try:
      t=subprocess.check_output(["pdftotext","-f",str(p),"-l",str(p),"-layout",path,"-"], text=True, errors="replace")
    except Exception:
      continue
    head="\n".join(t.splitlines()[:30])
    low=t[:1500].lower()
    for key, needle in needles:
      if key in found: continue
      if needle.lower() in low:
        found[key]=p
        print(f"  PDF {p}: matched {key} | {head[:140].replace(chr(10),' / ')}")
  mid=pages//2
  t=subprocess.check_output(["pdftotext","-f",str(mid),"-l",str(mid),path,"-"], text=True, errors="replace")
  alnum=sum(c.isalnum() for c in t)
  print(f"  mid_page={mid} alnum_chars={alnum}")
  print(f"  mid_sample={t[:180]!r}")
