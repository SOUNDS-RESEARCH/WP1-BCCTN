import torch
import torch.nn as nn
import torch.functional as F
from torch.nn import Module
from DCNN.feature_extractors import Stft, IStft
from torch_stoi import NegSTOILoss




EPS = 1e-6


class BinauralLoss(Module):
    def __init__(self, win_len=400,
                 win_inc=100, fft_len=512, sr=16000,
                 ild_weight=0.1, ipd_weight=1, stoi_weight=0, 
                  snr_loss_weight=1):

        super().__init__()
        self.stft = Stft(fft_len, win_inc, win_len)
        self.istft = IStft(fft_len, win_inc, win_len)
        self.stoi_loss = NegSTOILoss(sample_rate=sr)
       
        self.ild_weight = ild_weight
        self.ipd_weight = ipd_weight
        self.stoi_weight = stoi_weight
        self.snr_loss_weight = snr_loss_weight

        
    def forward(self, model_output, targets):
        target_stft_l = self.stft(targets[:, 0])
        target_stft_r = self.stft(targets[:, 1])
        

        output_stft_l = self.stft(model_output[:, 0])
        output_stft_r = self.stft(model_output[:, 1])


        loss = 0
        if self.snr_loss_weight > 0:
            
            snr_l = snr_loss(model_output[:, 0], targets[:, 0])
            snr_r = snr_loss(model_output[:, 1], targets[:, 1])
          
            snr_loss_lr = - (snr_l + snr_r)/2
           
            bin_snr_loss = self.snr_loss_weight*snr_loss_lr
            
            print('\n SNR Loss = ', bin_snr_loss)
            loss += bin_snr_loss
        
        if self.stoi_weight > 0:
            stoi_l = self.stoi_loss(model_output[:, 0], targets[:, 0])
            stoi_r = self.stoi_loss(model_output[:, 1], targets[:, 1])

            stoi_loss = (stoi_l+stoi_r)/2
            bin_stoi_loss = self.stoi_weight*stoi_loss.mean()
            print('\n STOI Loss = ', bin_stoi_loss)
            loss += bin_stoi_loss

        if self.ild_weight > 0:
            ild_loss = ild_loss_db(target_stft_l.abs(), target_stft_r.abs(),
                                   output_stft_l.abs(), output_stft_r.abs())
            
            bin_ild_loss = self.ild_weight*ild_loss
            print('\n ILD Loss = ', bin_ild_loss)
            loss += bin_ild_loss

        if self.ipd_weight > 0:
            ipd_loss = ipd_loss_rads(target_stft_l, target_stft_r,
                                     output_stft_l, output_stft_r)
            bin_ipd_loss = self.ipd_weight*ipd_loss
            
            print('\n IPD Loss = ', bin_ipd_loss)
            loss += bin_ipd_loss
        
        return loss
        
        
        
        
        
        
        
        
class Loss(Module):
    def __init__(self, loss_mode="SI-SNR", win_len=400,
                 win_inc=100,
                 fft_len=512,
                 win_type="hann",
                 fix=True, sr=16000,
                 STOI_weight=1,
                 SNR_weight=0.1):
        super().__init__()
        self.loss_mode = loss_mode
        self.stft = Stft(win_len, win_inc, fft_len,
                         win_type, "complex", fix=fix)
        self.stoi_loss = NegSTOILoss(sample_rate=sr)
        self.STOI_weight = STOI_weight
        self.SNR_weight = SNR_weight

    def forward(self, model_output, targets):
        if self.loss_mode == "MSE":
            b, d, t = model_output.shape
            targets[:, 0, :] = 0
            targets[:, d // 2, :] = 0
            return F.mse_loss(model_output, targets, reduction="mean") * d

        elif self.loss_mode == "SI-SNR":
            # return -torch.mean(snr_loss(model_output, targets))
            return -(snr_loss(model_output, targets))

        elif self.loss_mode == "MAE":
            gth_spec, gth_phase = self.stft(targets)
            b, d, t = model_output.shape
            return torch.mean(torch.abs(model_output - gth_spec)) * d

        elif self.loss_mode == "STOI-SNR":
            loss_batch = self.stoi_loss(model_output, targets)
            return -(self.SNR_weight*snr_loss(model_output, targets)) + self.STOI_weight*loss_batch.mean()


def l2_norm(s1, s2):
    norm = torch.sum(s1 * s2, -1, keepdim=True)
    return norm


def snr_loss(s1, s_target, eps=EPS, reduce_mean=True):
    
    e_nosie = s1 - s_target
    target_norm = l2_norm(s_target, s_target)
    noise_norm = l2_norm(e_nosie, e_nosie)
    snr = 10 * torch.log10((target_norm) / (noise_norm + eps) + eps)
    snr_norm = snr  # /max(snr)
    if reduce_mean:
        snr_norm = torch.mean(snr_norm)

    return snr_norm


def ild_db(s1, s2, eps=EPS):
    # s1 = _avg_signal(s1, avg_mode)
    # s2 = _avg_signal(s2, avg_mode)

    l1 = 20*torch.log10(s1 + eps)
    l2 = 20*torch.log10(s2 + eps)
    ild_value = (l1 - l2)

    return ild_value


def ild_loss_db(target_stft_l, target_stft_r,
                output_stft_l, output_stft_r, avg_mode=None):
    # amptodB = T.AmplitudeToDB(stype='amplitude')

    target_ild = ild_db(target_stft_l.abs(), target_stft_r.abs())
    output_ild = ild_db(output_stft_l.abs(), output_stft_r.abs())
    mask = speechMask(target_stft_l,target_stft_r,threshold=20)
    
    ild_loss = (target_ild - output_ild).abs()
    # breakpoint()
    masked_ild_loss = ((ild_loss * mask).sum(dim=2)).sum(dim=1)/(mask.sum(dim=2)).sum(dim=1)
   
    return masked_ild_loss.mean()

def msc_loss(target_stft_l, target_stft_r,
                output_stft_l, output_stft_r):
    
    

    # Calculate the Auto-Power Spectral Density (APSD) for left and right signals
    # Calculate the Auto-Power Spectral Density (APSD) for left and right signals
    cpsd = target_stft_l * target_stft_r.conj()
    cpsd_op = output_stft_l * output_stft_r.conj()
    
    # Calculate the Aucpsd = target_stft_l * target_stft_r.conj()to-Power Spectral Density (APSD) for left and right signals
    left_apsd = target_stft_l * target_stft_l.conj()
    right_apsd = target_stft_r * target_stft_r.conj()
    
    left_apsd_op = output_stft_l * output_stft_l.conj()
    right_apsd_op = output_stft_r * output_stft_r.conj()
    
    # Calculate the Magnitude Squared Coherence (MSC)
    msc_target = torch.abs(cpsd)**2 / ((left_apsd.abs() * right_apsd.abs())+1e-8)
    msc_output = torch.abs(cpsd_op)**2 / ((left_apsd_op.abs() * right_apsd_op.abs())+1e-8)
    
    mask = speechMask(target_stft_l,target_stft_r,threshold=20)
    
    msc_error = (msc_target - msc_output).abs()
    


    # Plot the MSC values as a function of frequency
    
    
    # breakpoint()
    # masked_msc_error = ((msc_error * mask).sum(dim=2)).sum(dim=1)/(mask.sum(dim=2)).sum(dim=1)
    
    return msc_error.mean()
    

def ipd_rad(s1, s2, eps=EPS, avg_mode=None):
    # s1 = _avg_signal(s1, avg_mode)
    # s2 = _avg_signal(s2, avg_mode)

    ipd_value = ((s1 + eps)/(s2 + eps)).angle()

    return ipd_value


def ipd_loss_rads(target_stft_l, target_stft_r,
                  output_stft_l, output_stft_r, avg_mode=None):
    # amptodB = T.AmplitudeToDB(stype='amplitude')
    target_ipd = ipd_rad(target_stft_l, target_stft_r, avg_mode=avg_mode)
    output_ipd = ipd_rad(output_stft_l, output_stft_r, avg_mode=avg_mode)

    ipd_loss = ((target_ipd - output_ipd).abs())

    mask = speechMask(target_stft_l,target_stft_r, threshold=20)
    
    masked_ipd_loss = ((ipd_loss * mask).sum(dim=2)).sum(dim=1)/(mask.sum(dim=2)).sum(dim=1)
    return masked_ipd_loss.mean()

def comp_loss_old(target_stft_l,target_stft_r,output_stft_l, output_stft_r,c=0.3):
    
    # EPS = 0+1e-10j
    target_stft_l_abs = torch.nan_to_num(target_stft_l.abs(), nan=0,posinf=0,neginf=0)
    output_stft_l_abs = torch.nan_to_num(output_stft_l.abs(), nan=0,posinf=0,neginf=0)
    target_stft_r_abs = torch.nan_to_num(target_stft_r.abs(), nan=0,posinf=0,neginf=0)
    output_stft_r_abs = torch.nan_to_num(output_stft_r.abs(), nan=0,posinf=0,neginf=0)
    
    loss_l = torch.abs(torch.pow(target_stft_l_abs,c) * torch.exp(1j*(target_stft_l.angle())) - torch.pow(output_stft_l_abs,c) * torch.exp(1j*(output_stft_l.angle())))
    loss_r = torch.abs(torch.pow(target_stft_r_abs,c) * torch.exp(1j*(target_stft_r.angle())) - torch.pow(output_stft_r_abs,c) * torch.exp(1j*(output_stft_r.angle())))
    # breakpoint()
    loss_l = torch.norm(loss_l,p='nuc')
    loss_r = torch.norm(loss_r,p='nuc')
    comp_loss_value = loss_l.mean() + loss_r.mean()
    
    
    return comp_loss_value

def comp_loss(target, output, comp_exp=0.3):
    
    EPS = 1e-6
    # target = torch.nan_to_num(target, nan=0,posinf=0,neginf=0)
    # output = torch.nan_to_num(output, nan=0,posinf=0,neginf=0)
    # target = target + EPS
    # output = output + EPS
    loss_comp = (
                    output.abs().pow(comp_exp) * output / (output.abs() + EPS) 
                    - target.abs().pow(comp_exp) * target / (target.abs() + EPS) 
                    )
    
    # loss_comp = torch.nan_to_num(loss_comp, nan=0,posinf=0,neginf=0)
    # breakpoint()
    loss_comp = torch.linalg.norm(loss_comp,ord=2,dim=(1,2))
    
    # loss_comp = loss_comp.pow(2).mean()
    
    return loss_comp.mean()

def speechMask(stft_l,stft_r, threshold=15):
    # breakpoint()
    _,_,time_bins = stft_l.shape
    thresh_l,_ = (((stft_l.abs())**2)).max(dim=2) 
    thresh_l_db = 10*torch.log10(thresh_l) - threshold
    thresh_l_db=thresh_l_db.unsqueeze(2).repeat(1,1,time_bins)
    
    thresh_r,_ = (((stft_r.abs())**2)).max(dim=2) 
    thresh_r_db = 10*torch.log10(thresh_r) - threshold
    thresh_r_db=thresh_r_db.unsqueeze(2).repeat(1,1,time_bins)
    
    
    bin_mask_l = BinaryMask(threshold=thresh_l_db)
    bin_mask_r = BinaryMask(threshold=thresh_r_db)
    
    mask_l = bin_mask_l(20*torch.log10((stft_l.abs())))
    mask_r = bin_mask_r(20*torch.log10((stft_r.abs())))
    mask = torch.bitwise_and(mask_l.int(), mask_r.int())
    
    return mask



def _avg_signal(s, avg_mode):
    if avg_mode == "freq":
        return s.mean(dim=1)
    elif avg_mode == "time":
        return s.mean(dim=2)
    elif avg_mode == None:
        return s


class BinaryMask(Module):
    def __init__(self, threshold=0.5):
        super(BinaryMask, self).__init__()
        self.threshold = threshold

    def forward(self, magnitude):
        # Compute the magnitude of the complex spectrogram
        # magnitude = torch.sqrt(spectrogram[:,:,0]**2 + spectrogram[:,:,1]**2)

        # Create a binary mask by thresholding the magnitude
        mask = (magnitude > self.threshold).float()
        # breakpoint()
        return mask


class STFT(Module):
    def __init__(self, win_len=400, win_inc=100,
                 fft_len=512):
        self.win_len = win_len
        self.win_inc = win_inc
        self.fft_len = fft_len

        super().__init__()

    def forward(self, x):
        stft = torch.stft(x, self.fft_len, hop_length=self.win_inc,
                          win_length=self.win_len, return_complex=True)
        return stft


class ISTFT(Module):
    def __init__(self, win_len=400, win_inc=100,
                 fft_len=512):
        self.win_len = win_len
        self.win_inc = win_inc
        self.fft_len = fft_len

        super().__init__()

    def forward(self, x):
        istft = torch.istft(x, self.fft_len, hop_length=self.win_inc,
                            win_length=self.win_len, return_complex=False)
        return istft

def complex_mse_loss(output, target):
    return ((output - target)**2).mean(dtype=torch.complex64)

class CLinear(nn.Module):
    def __init__(self, size_in, size_out):
        super().__init__()
        self.weights = nn.Parameter(torch.randn(size_in, size_out, dtype=torch.complex64))
        self.bias = nn.Parameter(torch.zeros(size_out, dtype=torch.complex64))

    def forward(self, x):
        if not x.dtype == torch.complex64: x = x.type(torch.complex64)
        return x@self.weights + self.bias
    
    
    
    

import matplotlib.pyplot as plt

# def magnitude_squared_coherence(left_signal, right_signal, n_fft=1024, hop_length=256):
#     # ... (code for calculating MSC, as previously shown) ...

# # Example usage


# msc = msc_loss(left_signal, right_signal)

# # Create a frequency axis for the plot (assuming a sample rate of 44100 Hz)
