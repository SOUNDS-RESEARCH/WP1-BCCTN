from omegaconf import OmegaConf
import torch

from torch.optim.lr_scheduler import MultiStepLR
from DCNN.models.binaural_attention_model import BinauralAttentionDCNN
from DCNN.models.model import DCNN
from DCNN.loss import BinauralLoss, Loss
from DCNN.utils.base_trainer import (
    BaseTrainer, BaseLightningModule
)


class DCNNTrainer(BaseTrainer):
    def __init__(self, config):
        lightning_module = DCNNLightningModule(config)
        super().__init__(lightning_module,
                         config["training"]["n_epochs"],
                         early_stopping_config=config["training"]["early_stopping"],
                         checkpoint_path=None,
                        #  strategy=config["training"]["strategy"],
                         accelerator=config["training"]["accelerator"])
                        # accelerator='mps')

    def fit(self, train_dataloaders, val_dataloaders=None):
        super().fit(self._lightning_module, train_dataloaders,
                    val_dataloaders=val_dataloaders)

    def test(self, test_dataloaders):
        super().test(self._lightning_module, test_dataloaders, ckpt_path="best")


class DCNNLightningModule(BaseLightningModule):
    """This class abstracts the
       training/validation/testing procedures
       used for training a DCNN
    """

    def __init__(self, config):
        config = OmegaConf.to_container(config)
        self.config = config

        if config["model"]["binaural"]:
            if config["model"]["attention"]:
                model = model = BinauralAttentionDCNN(**self.config["model"])
            else:
                model = BinauralAttentionDCNN(**self.config["model"])
            loss = BinauralLoss(
            
                ild_weight=self.config["model"]["ild_weight"],
                ipd_weight=self.config["model"]["ipd_weight"],
                
                stoi_weight=config["model"]["stoi_weight"],
                
                snr_loss_weight=self.config["model"]["snr_loss_weight"],
              
                )
        else:    
            model = DCNN(**self.config["model"])

            loss = Loss(loss_mode=self.config["model"]["loss_mode"],
                        STOI_weight=self.config["model"]["STOI_weight"],
                        SNR_weight=self.config["model"]["snr_weight"])

        super().__init__(model, loss)

    def configure_optimizers(self):
        lr = self.config["training"]["learning_rate"]
        decay_step = self.config["training"]["learning_rate_decay_steps"]
        decay_value = self.config["training"]["learning_rate_decay_values"]

        optimizer = torch.optim.Adam(self.parameters(), lr=lr)
        scheduler = MultiStepLR(optimizer, decay_step, decay_value)

        return [optimizer], [scheduler]
