import shutil, os, sys

def find_soffice():
    soff = shutil.which('soffice') or shutil.which('soffice.exe')
    if soff:
        return soff
    paths = [
        r'C:\Program Files\LibreOffice\program\soffice.exe',
        r'C:\Program Files (x86)\LibreOffice\program\soffice.exe',
        r'C:\Program Files\LibreOffice 7\program\soffice.exe',
        r'C:\Program Files\LibreOffice 24\program\soffice.exe',
    ]
    for p in paths:
        if os.path.exists(p):
            return p
    return None

def find_pdftoppm():
    p = shutil.which('pdftoppm') or shutil.which('pdftoppm.exe')
    if p:
        return p
    paths = [
        r'C:\Program Files\poppler\bin\pdftoppm.exe',
        r'C:\poppler\bin\pdftoppm.exe',
        r'C:\Program Files (x86)\poppler\bin\pdftoppm.exe',
    ]
    for pt in paths:
        if os.path.exists(pt):
            return pt
    return None

soff = find_soffice()
pdft = find_pdftoppm()

print("soffice:", soff)
print("pdftoppm:", pdft)
