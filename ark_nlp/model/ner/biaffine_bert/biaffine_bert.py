import time
import torch
import math
import torch.nn.functional as F
from torch import nn
from transformers import BertModel
from transformers import BertPreTrainedModel
from ark_nlp.nn.base.bert import BertForTokenClassification
from ark_nlp.nn.layer.biaffine_block import Biaffine


class BiaffineBert(BertForTokenClassification):
    """
    基于Biaffine的命名实体模型

    :param config: (obejct) 模型的配置对象
    :param bert_trained: (bool) bert参数是否可训练，默认可训练

    :returns: 

    Reference:
        [1] Named Entity Recognition as Dependency Parsing
        [2] https://github.com/suolyer/PyTorch_BERT_Biaffine_NER
    """ 
    def __init__(
        self, 
        config, 
        encoder_trained=True,
        biaffine_hidden_size=128,
        lstm_dropout=0.4
    ):
        super(BiaffineErnie, self).__init__(config)
        
        self.num_labels = config.num_labels
        
        self.bert = BertModel(config)
        
        for param in self.bert.parameters():
            param.requires_grad = encoder_trained 
                        
        self.lstm=torch.nn.LSTM(input_size=config.hidden_size,
                                hidden_size=config.hidden_size,
                                num_layers=1,
                                batch_first=True,
                                dropout=lstm_dropout,
                                bidirectional=True)
            
        self.start_encoder = torch.nn.Sequential(torch.nn.Linear(in_features=2*config.hidden_size, 
                                                                 out_features=biaffine_hidden_size),
                                                 torch.nn.ReLU())
        
        self.end_encoder = torch.nn.Sequential(torch.nn.Linear(in_features=2*config.hidden_size, 
                                                               out_features=biaffine_hidden_size),
                                               torch.nn.ReLU())            
       
        self.biaffne = Biaffine(biaffine_hidden_size, self.num_labels)
        
        self.reset_params()

    def reset_params(self):
        nn.init.xavier_uniform_(self.start_encoder[0].weight)
        nn.init.xavier_uniform_(self.end_encoder[0].weight)

    def forward(
        self, 
        input_ids=None,
        attention_mask=None,
        token_type_ids=None,
        **kwargs
    ):
        outputs = self.bert(input_ids,
                            attention_mask=attention_mask,
                            token_type_ids=token_type_ids,
                            return_dict=True, 
                            output_hidden_states=True
                           ).hidden_states
        

        sequence_output = outputs[-1]
        
        # lstm编码
        sequence_output, _ = self.lstm(sequence_output)
        
        start_logits = self.start_encoder(sequence_output) 
        end_logits = self.end_encoder(sequence_output) 

        span_logits = self.biaffne(start_logits, end_logits)
        span_logits = span_logits.contiguous()
        
        return span_logits