"""
# Copyright 2020 Xiang Wang, Inc. All Rights Reserved
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at 
# http://www.apache.org/licenses/LICENSE-2.0

Author: Xiang Wang, xiangking1995@163.com
Status: Active
"""

import numpy as np
import torch
import torch.nn as nn
import torch.optim as optim
from torch.optim import lr_scheduler
from torch.autograd import Variable, grad
from torch.utils.data import DataLoader, Dataset
import torch.nn.functional as F

import tqdm
from tqdm import tqdm
import sklearn.metrics as sklearn_metrics

from ..loss_function import get_loss
from ..optimizer import get_optimizer
from ._task import Task


class SequenceClassificationTask(Task):
    
    def __init__(self, *args, **kwargs):
        
        super(SequenceClassificationTask, self).__init__(*args, **kwargs)
        self.module.task = 'SequenceClassification'

    def _on_train_begin(
        self, 
        train_data, 
        validation_data, 
        batch_size,
        lr, 
        params, 
        logs,
        shuffle,
        inputs_cols=None,
        **kwargs
    ):
        if self.class_num == None:
            self.class_num = train_data.class_num  
        
        if inputs_cols == None:
            self.inputs_cols = train_data.dataset_cols
        else:
            self.inputs_cols = inputs_cols
            
        train_generator = DataLoader(train_data, batch_size=batch_size, shuffle=True, collate_fn=self._collate_fn)
        self.train_generator_lenth = len(train_generator)
            
        self.optimizer = get_optimizer(self.optimizer, self.module, lr, params)
        self.optimizer.zero_grad()
            
        self.module.train()
        
        self._on_train_begin_record(logs, **kwargs)
        
        return train_generator
    
    def _on_train_begin_record(self, logs, **kwargs):
        
        logs['tr_loss'] = 0
        logs['logging_loss'] = 0
        
        return logs
    
    def _on_epoch_begin(self, logs, **kwargs):
        
        self.module.train()
        
        self._on_epoch_begin_record(logs)
            
    def _on_epoch_begin_record(self, logs):
        
        logs['b_loss'] = 0
        logs['b_acc'] = 0
        logs['nb_tr_examples'] = 0
        logs['nb_tr_steps'] = 0
        
        return logs
        
    def _on_step_begin(
        self, 
        epoch, 
        step, 
        inputs, 
        logs, 
        **kwargs
    ):
        self._on_step_begin_record(epoch, step, inputs, logs, **kwargs)
    
    def _on_step_begin_record(
        self, 
        epoch, 
        step, 
        inputs, 
        logs, 
        **kwargs
    ):
        pass
            
    def _compute_loss(
        self, 
        inputs, 
        labels, 
        logits, 
        logs=None,
        verbose=True,
        **kwargs
    ):        
        loss = self.loss_function(logits, labels)     
        
        if logs:
            self._compute_loss_record(inputs, labels, logits, loss, logs, verbose, **kwargs)
                
        return loss
    
    def _compute_loss_record(
        self,
        inputs, 
        labels, 
        logits, 
        loss, 
        logs,
        verbose,
        **kwargs
    ):        
        logs['nb_tr_examples'] += len(labels)
        
        if verbose:
            with torch.no_grad():
                _, preds = torch.max(logits, 1)
                logs['b_acc'] += torch.sum(preds == labels).item()
                
        logs['b_loss'] += loss.item() * len(labels)
        logs['nb_tr_steps'] += 1
        
        return logs

    def _on_backward(
        self, 
        inputs, 
        labels, 
        logits, 
        loss, 
        logs,
        **kwargs
    ):
                
        loss.backward() 
        
        self._on_backward_record(logs)
        
        return loss
    
    def _on_optimize(self, step, logs, **kwargs):
        self.optimizer.step()  # 更新权值
        if self.scheduler:
            self.scheduler.step()  # 更新学习率
                
        self.optimizer.zero_grad()  # 清空梯度
        
        self._on_optimize_record(logs)
        
        return step
    
    def _on_step_end(
        self, 
        step,
        logs,
        verbose=True,
        print_step=100,
        **kwargs
    ):
        if verbose and (step + 1) % print_step == 0:
            print('[{}/{}],train loss is:{:.6f},train acc is:{:.6f}'.format(
                step, 
                self.train_generator_lenth,
                logs['b_loss'] / logs['nb_tr_steps'],
                logs['b_acc'] / logs['nb_tr_examples']))
            
        self._on_step_end_record(logs)
            
    def _on_epoch_end(
        self, 
        epoch,
        logs,
        verbose=True,
        **kwargs
    ):
        if verbose:
            print('epoch:[{}],train loss is:{:.6f},train acc is:{:.6f} \n'.format(
                epoch,
                logs['b_loss'] / logs['nb_tr_steps'],
                logs['b_acc'] / logs['nb_tr_examples']))  
            
        self._on_epoch_end_record(logs)
            
    def _on_evaluate_begin(
        self, 
        validation_data, 
        batch_size, 
        logs, 
        shuffle, 
        **kwargs
    ):
        
        generator = DataLoader(validation_data, batch_size=batch_size, shuffle=False, collate_fn=self._collate_fn)
        
        self.module.eval()
        
        self._on_evaluate_begin_record(logs, **kwargs)
        
        return generator
    
    def _on_evaluate_begin_record(self, logs, **kwargs):
        
        logs['eval_loss'] = 0
        logs['eval_acc']  = 0
        logs['nb_eval_steps']  = 0
        logs['nb_eval_examples']  = 0
        
        logs['labels'] = []
        logs['logits'] = []
        
        return logs     
                    
    def _on_evaluate_step_end(self, inputs, labels, logits, loss, logs, **kwargs):
        
        _, preds = torch.max(logits, 1)
        
        logs['labels'].append(labels)
        logs['logits'].append(logits)
            
        logs['nb_eval_examples'] +=  len(labels)
        logs['nb_eval_steps']  += 1
        logs['eval_loss'] += loss.item() * len(labels)
        logs['eval_acc'] += torch.sum(preds == labels.data).item()
        
        return logs
    
    def _on_evaluate_end(
        self, 
        validation_data,
        logs,
        epoch=1,
        is_evaluate_print=True,
        **kwargs):
        
        labels_ = torch.cat(logs['labels'], dim=0).cpu()
        preds_ = torch.argmax(torch.cat(logs['logits'], dim=0), -1).cpu()

        
        f1_score = sklearn_metrics.f1_score(labels_, preds_, average='macro')
        report_ = sklearn_metrics.classification_report(labels_, preds_, target_names = [str(category_) for category_ in validation_data.categories])
        confusion_matrix_ = sklearn_metrics.confusion_matrix(labels_, preds_)
        
        if is_evaluate_print:
            print('classification_report: \n', report_)
            print('confusion_matrix_: \n', confusion_matrix_)
            print('test loss is:{:.6f},test acc is:{:.6f},f1_score is:{:.6f}'.format(logs['eval_loss'] / logs['nb_eval_steps'], 
                                                                                     logs['eval_acc'] / logs['nb_eval_examples'] ,
                                                                                     f1_score))
    def _get_module_inputs_on_train(
        self,
        inputs,
        labels,
        **kwargs
    ):
        return {col: inputs[col].to(self.device) for col in self.inputs_cols}

    def _get_module_label_on_train(
        self,
        inputs,
        **kwargs
    ):
        return inputs['label_ids'].to(self.device)

    def _get_module_inputs_on_eval(
        self,
        inputs,
        labels,
        **kwargs
    ):
        return {col: inputs[col].to(self.device) for col in self.inputs_cols}

    def _get_module_label_on_eval(
        self,
        inputs,
        **kwargs
    ):
        return inputs['label_ids'].to(self.device)

    def fit(
        self, 
        train_data=None, 
        validation_data=None, 
        lr=1e-3,
        params=None,
        batch_size=32,
        epochs=1,
        **kwargs
    ):
        logs = dict()
        
        train_generator = self._on_train_begin(train_data, validation_data, batch_size, lr, params, logs, shuffle=True, **kwargs)
                
        for epoch in range(epochs):
            
            self._on_epoch_begin(logs, **kwargs)
            
            for step, inputs in enumerate(tqdm(train_generator)):
                
                self._on_step_begin(epoch, step, inputs, logs, **kwargs)
                                
                labels = self._get_module_label_on_train(inputs, **kwargs)
                inputs = self._get_module_inputs_on_train(inputs, labels, **kwargs)
                                
                # forward
                logits = self.module(**inputs)

                # 计算损失
                loss = self._compute_loss(inputs, labels, logits, logs, **kwargs)
                                                
                # loss backword
                loss = self._on_backward(inputs, labels, logits, loss, logs, **kwargs)
                
                # optimize
                step = self._on_optimize(step, logs, **kwargs)
                
                # setp evaluate
                self._on_step_end(step, logs, **kwargs)
            
            self._on_epoch_end(epoch, logs, **kwargs)
            
            if validation_data is not None:
                self.evaluate(validation_data, **kwargs)

    def predict(
        self, 
        test_data, 
        batch_size=16, 
        shuffle=False, 
        is_proba=False
    ):
        
        preds = []
        probas=[]
        
        self.module.eval()
        generator = DataLoader(test_data, batch_size=batch_size, shuffle=False, collate_fn=self._collate_fn)
        
        for step, inputs in enumerate(generator):
            inputs = {col: inputs[col].to(self.device) for col in self.inputs_cols}
            logits = self.module(**inputs)

            preds.extend(torch.max(logits, 1)[1].cpu().numpy())  
            if is_proba:
                probas.extend(F.softmax(logits, 1).cpu().detach().numpy())  

        if is_proba:
            return preds, probas
        
        return preds
    
    def predict_proba(
        self, 
        test_data, 
        batch_size=16, 
        shuffle=False
    ):
        return self.predict(test_data, batch_size, shuffle, is_proba=True)[-1]
    
    def evaluate(
        self, 
        validation_data, 
        evaluate_batch_size=16, 
        return_pred=False, 
        **kwargs
    ):
        logs = dict()
        
        generator = self._on_evaluate_begin(validation_data, evaluate_batch_size, logs, shuffle=False, **kwargs)
                
        with torch.no_grad():
                        
            for step, inputs in enumerate(generator):
                
                labels = self._get_module_label_on_eval(inputs, **kwargs)
                inputs = self._get_module_inputs_on_eval(inputs, labels, **kwargs)
                
                # forward
                logits = self.module(**inputs)
                
                # compute loss
                loss = self._compute_loss(inputs, labels, logits, **kwargs)
                
                self._on_evaluate_step_end(inputs, labels, logits, loss, logs, **kwargs)
                
        self._on_evaluate_end(validation_data, logs)