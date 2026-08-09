import os, sys, shutil

def pptx_to_pngs_win32(pptx_path, outdir, prefix='slide'):
    import win32com.client
    os.makedirs(outdir, exist_ok=True)
    abs_pptx = os.path.abspath(pptx_path)
    abs_out = os.path.abspath(outdir)
    
    ppt = win32com.client.Dispatch('PowerPoint.Application')
    # Open presentation hidden / read only
    pres = ppt.Presentations.Open(abs_pptx, WithWindow=False)
    
    # Create temp dir for export
    tmp_export = os.path.join(abs_out, '_tmp_export')
    os.makedirs(tmp_export, exist_ok=True)
    
    # 18 = ppSaveAsPNG
    pres.SaveAs(tmp_export, 18)
    pres.Close()
    ppt.Quit()
    
    # Rename/format slide PNGs to standard prefix format (e.g. slide-01.png)
    exp_files = sorted(os.listdir(tmp_export), key=lambda f: int(re.search(r'\d+', f).group()) if re.search(r'\d+', f) else 0)
    out_files = []
    for idx, fname in enumerate(exp_files):
        if fname.lower().endswith('.png') or fname.lower().endswith('.jpg'):
            src = os.path.join(tmp_export, fname)
            dst_name = f"{prefix}-{idx+1:03d}.png"
            dst = os.path.join(abs_out, dst_name)
            shutil.move(src, dst)
            out_files.append(dst)
            
    shutil.rmtree(tmp_export, ignore_errors=True)
    return out_files

src = r'c:\Users\Pratibha\Downloads\Artificial Intelligence (AI) is technology that enables machines and software to learn, think, analyze, and make decisions like humans..pptx'
out = r'c:\Users\Pratibha\OneDrive\Desktop\AI-Training-Platform-Avatar\lumen-studio-v5\test_out_pngs'
res = pptx_to_pngs_win32(src, out)
print(f"Exported {len(res)} PNG images:")
for r in res:
    print("  ", r)
