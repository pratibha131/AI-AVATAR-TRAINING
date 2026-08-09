"""Minimal Wav2Lip network definition (inference only).

Architecture matching the public Wav2Lip checkpoints (Rudrabha/Wav2Lip).
NOTE: the pretrained weights are released for research / personal use;
commercial deployments should obtain a license from the authors or use a
commercial avatar API instead.
"""
import torch
from torch import nn
from torch.nn import functional as F


class Conv2d(nn.Module):
    def __init__(self, cin, cout, kernel_size, stride, padding, residual=False):
        super().__init__()
        self.conv_block = nn.Sequential(
            nn.Conv2d(cin, cout, kernel_size, stride, padding),
            nn.BatchNorm2d(cout))
        self.act = nn.ReLU()
        self.residual = residual

    def forward(self, x):
        out = self.conv_block(x)
        if self.residual:
            out += x
        return self.act(out)


class Conv2dTranspose(nn.Module):
    def __init__(self, cin, cout, kernel_size, stride, padding, output_padding=0):
        super().__init__()
        self.conv_block = nn.Sequential(
            nn.ConvTranspose2d(cin, cout, kernel_size, stride, padding, output_padding),
            nn.BatchNorm2d(cout))
        self.act = nn.ReLU()

    def forward(self, x):
        return self.act(self.conv_block(x))


class Wav2Lip(nn.Module):
    def __init__(self):
        super().__init__()
        self.face_encoder_blocks = nn.ModuleList([
            nn.Sequential(Conv2d(6, 16, 7, 1, 3)),
            nn.Sequential(Conv2d(16, 32, 3, 2, 1),
                          Conv2d(32, 32, 3, 1, 1, residual=True),
                          Conv2d(32, 32, 3, 1, 1, residual=True)),
            nn.Sequential(Conv2d(32, 64, 3, 2, 1),
                          Conv2d(64, 64, 3, 1, 1, residual=True),
                          Conv2d(64, 64, 3, 1, 1, residual=True),
                          Conv2d(64, 64, 3, 1, 1, residual=True)),
            nn.Sequential(Conv2d(64, 128, 3, 2, 1),
                          Conv2d(128, 128, 3, 1, 1, residual=True),
                          Conv2d(128, 128, 3, 1, 1, residual=True)),
            nn.Sequential(Conv2d(128, 256, 3, 2, 1),
                          Conv2d(256, 256, 3, 1, 1, residual=True),
                          Conv2d(256, 256, 3, 1, 1, residual=True)),
            nn.Sequential(Conv2d(256, 512, 3, 2, 1),
                          Conv2d(512, 512, 3, 1, 1, residual=True)),
            nn.Sequential(Conv2d(512, 512, 3, 1, 0),
                          Conv2d(512, 512, 1, 1, 0)),
        ])
        self.audio_encoder = nn.Sequential(
            Conv2d(1, 32, 3, 1, 1),
            Conv2d(32, 32, 3, 1, 1, residual=True),
            Conv2d(32, 32, 3, 1, 1, residual=True),
            Conv2d(32, 64, 3, (3, 1), 1),
            Conv2d(64, 64, 3, 1, 1, residual=True),
            Conv2d(64, 64, 3, 1, 1, residual=True),
            Conv2d(64, 128, 3, 3, 1),
            Conv2d(128, 128, 3, 1, 1, residual=True),
            Conv2d(128, 128, 3, 1, 1, residual=True),
            Conv2d(128, 256, 3, (3, 2), 1),
            Conv2d(256, 256, 3, 1, 1, residual=True),
            Conv2d(256, 512, 3, 1, 0),
            Conv2d(512, 512, 1, 1, 0))
        self.face_decoder_blocks = nn.ModuleList([
            nn.Sequential(Conv2d(512, 512, 1, 1, 0)),
            nn.Sequential(Conv2dTranspose(1024, 512, 3, 1, 0),
                          Conv2d(512, 512, 3, 1, 1, residual=True)),
            nn.Sequential(Conv2dTranspose(1024, 512, 3, 2, 1, 1),
                          Conv2d(512, 512, 3, 1, 1, residual=True),
                          Conv2d(512, 512, 3, 1, 1, residual=True)),
            nn.Sequential(Conv2dTranspose(768, 384, 3, 2, 1, 1),
                          Conv2d(384, 384, 3, 1, 1, residual=True),
                          Conv2d(384, 384, 3, 1, 1, residual=True)),
            nn.Sequential(Conv2dTranspose(512, 256, 3, 2, 1, 1),
                          Conv2d(256, 256, 3, 1, 1, residual=True),
                          Conv2d(256, 256, 3, 1, 1, residual=True)),
            nn.Sequential(Conv2dTranspose(320, 128, 3, 2, 1, 1),
                          Conv2d(128, 128, 3, 1, 1, residual=True),
                          Conv2d(128, 128, 3, 1, 1, residual=True)),
            nn.Sequential(Conv2dTranspose(160, 64, 3, 2, 1, 1),
                          Conv2d(64, 64, 3, 1, 1, residual=True),
                          Conv2d(64, 64, 3, 1, 1, residual=True)),
        ])
        self.output_block = nn.Sequential(
            Conv2d(80, 32, 3, 1, 1),
            nn.Conv2d(32, 3, 1, 1, 0),
            nn.Sigmoid())

    def forward(self, audio_sequences, face_sequences):
        B = audio_sequences.size(0)
        input_dim_size = len(face_sequences.size())
        if input_dim_size > 4:
            audio_sequences = torch.cat(
                [audio_sequences[:, i] for i in range(audio_sequences.size(1))], dim=0)
            face_sequences = torch.cat(
                [face_sequences[:, :, i] for i in range(face_sequences.size(2))], dim=0)
        audio_embedding = self.audio_encoder(audio_sequences)
        feats = []
        x = face_sequences
        for f in self.face_encoder_blocks:
            x = f(x)
            feats.append(x)
        x = audio_embedding
        for f in self.face_decoder_blocks:
            x = f(x)
            try:
                x = torch.cat((x, feats[-1]), dim=1)
            except Exception:
                raise
            feats.pop()
        x = self.output_block(x)
        if input_dim_size > 4:
            x = torch.split(x, B, dim=0)
            outputs = torch.stack(x, dim=2)
        else:
            outputs = x
        return outputs


def load_wav2lip(path, device='cpu'):
    ckpt = torch.load(path, map_location=device, weights_only=False)
    sd = ckpt['state_dict'] if 'state_dict' in ckpt else ckpt
    sd = {k.replace('module.', ''): v for k, v in sd.items()}
    model = Wav2Lip()
    model.load_state_dict(sd)
    model.eval()
    return model.to(device)
