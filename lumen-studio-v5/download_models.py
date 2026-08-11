"""Download the Wav2Lip lip-sync model (~430 MB) into ./models/."""
import os, urllib.request
here = os.path.dirname(os.path.abspath(__file__))
os.makedirs(os.path.join(here, 'models'), exist_ok=True)
url = 'https://github.com/anothermartz/Easy-Wav2Lip/releases/download/Prerequesits/Wav2Lip_GAN.pth'
dst = os.path.join(here, 'models', 'wav2lip_gan.pth')
print('downloading Wav2Lip weights…')
urllib.request.urlretrieve(url, dst)
print('done ->', dst)
