# @Author : bamtercelboo
# @Datetime : 2018/1/31 9:24
# @File : model_PNC.py
# @Last Modify Time : 2018/1/31 9:24
# @Contact : bamtercelboo@{gmail.com, 163.com}

"""
    FILE :  model_PNC.py
    FUNCTION : Part-of-Speech Tagging(POS), Named Entity Recognition(NER) and Chunking
"""

import torch
import torch.nn as nn
import torch.nn.functional as F
import numpy as np
from torch.autograd import Variable as Variable
from torch.nn.utils.rnn import pack_padded_sequence, pad_packed_sequence
import random
import torch.nn.init as init
import numpy as np
import time

from wheel.signatures import assertTrue

from DataUtils.Common import *
torch.manual_seed(seed_num)
random.seed(seed_num)


class PNC(nn.Module):

    def __init__(self, config):
        super(PNC, self).__init__()
        self.args = config
        self.cat_size = 5

        V = config.embed_num
        D = config.embed_dim
        C = config.class_num
        paddingId = config.paddingId

        self.embed = nn.Embedding(V, D, padding_idx=paddingId, max_norm=5)
        # self.embed = nn.Embedding(V, D)

        if config.pretrained_embed:
            self.embed.weight.data.copy_(config.pretrained_weight)
        # self.embed.weight.requires_grad = False

        self.dropout_embed = nn.Dropout(config.dropout_emb)
        self.dropout = nn.Dropout(config.dropout)

        # self.batchNorm = nn.BatchNorm1d(D * 5)

        self.bilstm = nn.LSTM(input_size=D * 5, hidden_size=config.lstm_hiddens, dropout=config.dropout, num_layers=config.lstm_layers,
                              bidirectional=True, bias=True)
        # self.init_lstm()
        # init.xavier_uniform(self.bilstm.all_weights[0][0])
        # self.bilstm.bias.uniform_(-np.sqrt(6 / (config.lstm_hiddens + 1)), np.sqrt(6 / (config.lstm_hiddens + 1)))

        # self.linear = nn.Linear(in_features=D * self.cat_size, out_features=C, bias=True)
        self.linear = nn.Linear(in_features=config.lstm_hiddens * 2, out_features=C, bias=True)
        # init.xavier_uniform(self.linear.weight)
        # self.linear.bias.data.uniform_(-np.sqrt(6 / (config.lstm_hiddens + 1)), np.sqrt(6 / (config.lstm_hiddens + 1)))

    def init_lstm(self):
        if self.bilstm.bidirectional is True:   weight = 2
        else:   weight = 1
        for i in range(weight):
            for j in range(2):
                init.xavier_uniform(self.bilstm.all_weights[i][j])

    def cat_embedding(self, x):
        # print("source", x)
        batch = x.size(0)
        word_size = x.size(1)
        cated_embed = torch.zeros(batch, word_size, self.args.embed_dim * self.cat_size)
        for id_batch in range(batch):
            batch_word_list = np.array(x[id_batch].data).tolist()
            batch_word_list.insert(0, [0] * self.args.embed_dim)
            batch_word_list.insert(1, [0] * self.args.embed_dim)
            batch_word_list.insert(word_size, [0] * self.args.embed_dim)
            batch_word_list.insert(word_size + 1, [0] * self.args.embed_dim)
            batch_word_embed = torch.from_numpy(np.array(batch_word_list)).type(torch.FloatTensor)
            cat_list = []
            for id_word in range(word_size):
                cat_list.append(torch.cat(batch_word_embed[id_word:(id_word + self.cat_size)]).unsqueeze(0))
            sentence_cated_embed = torch.cat(cat_list)
            cated_embed[id_batch] = sentence_cated_embed
        if self.args.use_cuda is True:
            cated_embed = Variable(cated_embed).cuda()
        else:
            cated_embed = Variable(cated_embed)
        # print("cated", cated_embed)
        return cated_embed

    def context_embed(self, embed, batch_features):
        context_indices = batch_features.context_indices
        B, T, WS = context_indices.size()
        B_embed, T_embed, dim = embed.size()
        if assertTrue((B == B_embed) and (T == T_embed)) is False:
            print("invalid argument")
            exit()
        print("context_indices", context_indices.size())
        print("BTWS", B, T, WS)
        # pad_embed = Variable(torch.zeros(B, dim))
        # print(pad_embed.size())
        # print((embed.view(B * T, -1)).size())
        # embed = torch.cat((embed.view(B * T, -1), pad_embed), 0)
        # print("embed", embed.size())
        # embed = embed.view(B * (T + B), -1)
        context_indices = context_indices.view(B, T * WS)
        if self.args.use_cuda is True:
            context_np = context_indices.data.cpu().numpy()
        else:
            context_np = np.copy(context_indices.data.numpy())
        # context_np = context_indices.data.numpy()
        for i in range(B):
            for j in range(T * WS):
                context_np[i][j] = T * i + context_np[i][j]
        if self.args.use_cuda is True:
            context_indices = Variable(torch.from_numpy(context_np)).cuda()
        else:
            context_indices = Variable(torch.from_numpy(context_np))
        context_indices = context_indices.view(context_indices.size(0) * context_indices.size(1))

        print(context_indices)
        embed = embed.view(B * T, dim)
        if self.args.use_cuda is True:
            pad_embed = Variable(torch.zeros(1, dim)).cuda()
        else:
            pad_embed = Variable(torch.zeros(1, dim))
        embed = torch.cat((embed, pad_embed), 0)
        print(embed.size())
        context_embed = torch.index_select(embed, 0, context_indices)
        context_embed = context_embed.view(B, T, -1)

        return context_embed

    def forward(self, batch_features):
        word = batch_features.word_features
        sentence_length = batch_features.sentence_length
        x = self.embed(word)  # (N,W,D)
        context_embed = self.context_embed(x, batch_features)
        context_embed = self.dropout_embed(context_embed)
        packed_embed = pack_padded_sequence(context_embed, sentence_length, batch_first=True)
        x, _ = self.bilstm(packed_embed)
        x, _ = pad_packed_sequence(x, batch_first=True)
        x = x[batch_features.desorted_indices]
        x = F.tanh(x)
        logit = self.linear(x)
        return logit

    # def forward(self, batch_features):
    #     word = batch_features.word_features
    #     sentence_length = batch_features.sentence_length
    #     x = self.embed(word)  # (N,W,D)
    #     start_time = time.time()
    #     cated_embed = self.cat_embedding(x)
    #     end_time = time.time()
    #     print("Time", end_time - start_time)
    #     # cated_embed = x
    #     cated_embed = self.dropout_embed(cated_embed)
    #     # cated_embed = self.dropout_embed(x)
    #     packed_embed = pack_padded_sequence(cated_embed, sentence_length, batch_first=True)
    #     x, _ = self.bilstm(packed_embed)
    #     x, _ = pad_packed_sequence(x, batch_first=True)
    #     x = x[batch_features.desorted_indices]
    #     x = F.tanh(x)
    #     logit = self.linear(x)
    #     return logit

