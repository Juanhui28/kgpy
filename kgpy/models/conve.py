"""
Implementation of ConvE. 

See paper for more details - https://arxiv.org/abs/1707.01476.
"""
import torch
import torch.nn.functional as F

from .base_emb_model import SingleEmbeddingModel


class ConvE(SingleEmbeddingModel):
    def __init__(self, 
        num_entities, 
        num_relations, 
        emb_dim=200, 
        filters=32,
        ker_sz=3,
        k_h=20,
        hidden_drop=.3,
        input_drop=.2,
        feat_drop=.2,
        margin=1, 
        regularization='l2',
        reg_weight=0,
        weight_init=None,
        loss_fn="bce"
    ):
        super().__init__(
            type(self).__name__,
            num_entities, 
            num_relations, 
            emb_dim, 
            margin, 
            regularization,
            reg_weight,
            weight_init, 
            loss_fn,
            True
        )
        
        self.inp_drop = torch.nn.Dropout(input_drop)
        self.hidden_drop = torch.nn.Dropout(hidden_drop)
        self.feature_map_drop = torch.nn.Dropout2d(feat_drop)

        # emb_dim = kernel_h * kernel_w
        self.k_h = k_h
        self.k_w = emb_dim // k_h
        self.filters = filters
        self.ker_sz = ker_sz

        # TODO: Determine why wrong
        # flat_sz_h = int(2*self.k_w) - self.ker_sz + 1
        # flat_sz_w = self.k_h - self.ker_sz + 1
        # self.hidden_size = flat_sz_h*flat_sz_w*filters
        self.hidden_size = 9728

        self.conv1 = torch.nn.Conv2d(1, filters, kernel_size=(ker_sz, ker_sz), stride=1, padding=0)
        self.bn0 = torch.nn.BatchNorm2d(1)
        self.bn1 = torch.nn.BatchNorm2d(32)
        self.bn2 = torch.nn.BatchNorm1d(emb_dim)

        self.register_parameter('b', torch.nn.Parameter(torch.zeros(num_entities)))

        self.fc = torch.nn.Linear(self.hidden_size, emb_dim)


    def score_hrt(self, triplets):
        """
        Pass through ConvE.

        Note: Only work for 1-N

        Parameters:
        -----------
            triplets: list
                List of triplets (rel, head)

        Returns:
        --------
        Tensor
            List of scores for triplets
        """
        e1_embedded  = self.entity_embeddings(triplets[:, 1]).view(-1, 1, self.k_h, self.k_w)
        rel_embedded = self.relation_embeddings(triplets[:, 0]).view(-1, 1, self.k_h, self.k_w)

        triplets = torch.cat([e1_embedded, rel_embedded], 2)

        stacked_inputs = self.bn0(triplets)
        x= self.inp_drop(stacked_inputs)
        x= self.conv1(x)
        x= self.bn1(x)
        x= F.relu(x)
        x = self.feature_map_drop(x)
        x = x.view(x.shape[0], -1)
        x = self.fc(x)
        x = self.hidden_drop(x)
        x = self.bn2(x)
        x = F.relu(x)
        x = torch.mm(x, self.entity_embeddings.weight.transpose(1,0))
        x += self.b.expand_as(x)
        pred = torch.sigmoid(x)

        return pred


    # TODO: For now just pass to score_hrt
    def score_head(self, triplets):
        """
        Get the score for a given set of triplets against *all possible* heads.
        
        Parameters:
        -----------
            triplets: list
                List of triplets

        Returns:
        --------
        Tensor
            List of scores for triplets
        """
        return self.score_hrt(triplets)


    # TODO: For now just pass to score_hrt
    def score_tail(self, triplets):
        """
        Get the score for a given set of triplets against *all possible* tails.

        Parameters:
        -----------
            triplets: list
                List of triplets

        Returns:
        --------
        Tensor
            List of scores for triplets
        """
        return self.score_hrt(triplets)
