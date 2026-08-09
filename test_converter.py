import os, sys, subprocess

def test_win32com():
    try:
        import win32com.client
        ppt = win32com.client.Dispatch('PowerPoint.Application')
        print("win32com PowerPoint COM object works!")
        ppt.Quit()
        return True
    except Exception as e:
        print("win32com error:", e)
        return False

def test_soffice():
    import shutil
    cmd = shutil.which('soffice') or shutil.which('soffice.exe')
    print("soffice found:", cmd)

def test_numeric_sorting():
    import slides
    files = ['Slide1.PNG', 'Slide10.PNG', 'Slide11.PNG', 'Slide2.PNG', 'Slide3.PNG']
    sorted_files = sorted(files, key=slides._num_sort_key)
    print("Numeric sorting test:", sorted_files)
    assert sorted_files == ['Slide1.PNG', 'Slide2.PNG', 'Slide3.PNG', 'Slide10.PNG', 'Slide11.PNG'], "Numeric sorting failed!"
    print("Numeric sorting test PASSED!")

test_win32com()
test_soffice()
test_numeric_sorting()
