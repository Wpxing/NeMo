# =============================================================================
# Copyright 2020 NVIDIA. All Rights Reserved.
# Copyright 2018 The Google AI Language Team Authors and
# The HuggingFace Inc. team.
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.
# =============================================================================

import argparse
import json
import os
import sys

import torch
print(os.path.join(os.path.dirname(__file__), '../../../../../../../../Megatron-LM'))
sys.path.append(os.path.join(os.path.dirname(__file__), '../../../../../../../../Megatron-LM'))
from megatron import get_args
from megatron.initialize import initialize_megatron
from megatron.model.bert_model import bert_attention_mask_func, bert_extended_attention_mask, bert_position_ids
from megatron.model.language_model import get_language_model
from megatron.model.utils import init_method_normal, scaled_init_method_normal

from nemo.backends.pytorch.nm import TrainableNM
from nemo.core.neural_types import ChannelType, NeuralType
from nemo.utils.decorators import add_port_docs


__all__ = ['MegatronBERT']


class MegatronBERT(TrainableNM):
    """
    MegatronBERT wraps around the Megatron Language model
    from https://github.com/NVIDIA/Megatron-LM

    Args:
        config_file (str): path to model configuration file.
        vocab_file (str): path to vocabulary file.
        tokenizer_type (str): tokenizer type, currently only 'BertWordPieceLowerCase' supported.
    """

    @property
    @add_port_docs()
    def input_ports(self):
        """Returns definitions of module input ports.
        input_ids: input token ids
        token_type_ids: segment type ids
        attention_mask: attention mask
        """
        return {
            "input_ids": NeuralType(('B', 'T'), ChannelType()),
            "attention_mask": NeuralType(('B', 'T'), ChannelType()),
            "token_type_ids": NeuralType(('B', 'T'), ChannelType(), optional=True),
        }

    @property
    @add_port_docs()
    def output_ports(self):
        """Returns definitions of module output ports.
        hidden_states: output embedding 
        """
        return {"hidden_states": NeuralType(('B', 'T', 'D'), ChannelType())}

    def __init__(
        self, config_file, vocab_file, tokenizer_type='BertWordPieceLowerCase', init_method_std=0.02, num_tokentypes=2
    ):

        super().__init__()

        if not os.path.exists(vocab_file):
            raise ValueError(f'Vocab file not found at {vocab_file}')

        if not os.path.exists(config_file):
            raise ValueError(f'Config file not found at {config_file}')
        with open(config_file) as json_file:
            config = json.load(json_file)

        megatron_args = {
            "num_layers": config['num-layers'],
            "hidden_size": config['hidden-size'],
            "num_attention_heads": config['num-attention-heads'],
            "max_position_embeddings": config['max-seq-length'],
            "tokenizer_type": tokenizer_type,
            "vocab_file": vocab_file,
        }

        initialize_megatron(None, megatron_args)
        init_method = init_method_normal(init_method_std)

        self.language_model, self._language_model_key = get_language_model(
            attention_mask_func=bert_attention_mask_func,
            num_tokentypes=num_tokentypes,
            add_pooler=False,
            init_method=init_method,
            scaled_init_method=scaled_init_method_normal(init_method_std, config['num-layers']),
        )

        self.language_model.to(self._device)
        self._hidden_size = self.language_model.hidden_size

    @property
    def hidden_size(self):
        """
            Property returning hidden size.

            Returns:
                Hidden size.
        """
        return self._hidden_size

    def forward(self, input_ids, attention_mask, token_type_ids):
        extended_attention_mask = bert_extended_attention_mask(
            attention_mask, next(self.language_model.parameters()).dtype
        )
        position_ids = bert_position_ids(input_ids)

        sequence_output = self.language_model(
            input_ids, position_ids, extended_attention_mask, tokentype_ids=token_type_ids
        )
        return sequence_output

    def restore_from(self, path, local_rank=0):
        self.language_model.load_state_dict(torch.load(path, map_location="cpu")['model'][self._language_model_key])
