"""
AASIST full-attention residual recursive encoder variant.
"""

import torch
import torch.nn as nn
import torch.nn.functional as F

from .AASIST import (CONV, GraphAttentionLayer, GraphPool,
                     HtrgGraphAttentionLayer, Residual_block)


class ResidualAttentionFusion(nn.Module):
    def __init__(self, source_channels, target_channels, attn_dim=None):
        super().__init__()

        if attn_dim is None:
            attn_dim = target_channels

        self.align_layers = nn.ModuleList([
            nn.Identity() if channels == target_channels else nn.Conv2d(
                channels, target_channels, kernel_size=1)
            for channels in source_channels
        ])
        self.query_proj = nn.Linear(target_channels, attn_dim)
        self.key_proj = nn.Linear(target_channels, attn_dim)
        self.score_proj = nn.Linear(attn_dim, 1)

    def forward(self, residuals):
        reference = residuals[-1]
        target_size = reference.shape[-2:]

        aligned = []
        descriptors = []
        for align_layer, residual in zip(self.align_layers, residuals):
            aligned_residual = align_layer(residual)
            if aligned_residual.shape[-2:] != target_size:
                aligned_residual = F.adaptive_avg_pool2d(aligned_residual, target_size)
            aligned.append(aligned_residual)
            descriptors.append(F.adaptive_avg_pool2d(aligned_residual, 1).flatten(1))

        query = self.query_proj(descriptors[-1])
        scores = []
        for descriptor in descriptors:
            score = self.score_proj(torch.tanh(query + self.key_proj(descriptor)))
            scores.append(score)

        attention = F.softmax(torch.cat(scores, dim=1), dim=1)

        fused = 0.0
        for idx, aligned_residual in enumerate(aligned):
            fused = fused + attention[:, idx].view(-1, 1, 1, 1) * aligned_residual

        return fused


class Model(nn.Module):
    def __init__(self, d_args):
        super().__init__()

        self.d_args = d_args
        filts = d_args["filts"]
        gat_dims = d_args["gat_dims"]
        pool_ratios = d_args["pool_ratios"]
        temperatures = d_args["temperatures"]

        self.conv_time = CONV(out_channels=filts[0],
                              kernel_size=d_args["first_conv"],
                              in_channels=1)
        self.first_bn = nn.BatchNorm2d(num_features=1)

        self.drop = nn.Dropout(0.5, inplace=True)
        self.drop_way = nn.Dropout(0.2, inplace=True)
        self.selu = nn.SELU(inplace=True)

        self.encoder_blocks = nn.ModuleList([
            Residual_block(nb_filts=filts[1], first=True),
            Residual_block(nb_filts=filts[2]),
            Residual_block(nb_filts=filts[3]),
            Residual_block(nb_filts=filts[4]),
            Residual_block(nb_filts=filts[4]),
            Residual_block(nb_filts=filts[4]),
        ])

        block_input_channels = [filts[1][0], filts[2][0], filts[3][0], filts[4][0], filts[4][0], filts[4][0]]
        block_output_channels = [filts[1][1], filts[2][1], filts[3][1], filts[4][1], filts[4][1], filts[4][1]]

        self.residual_attention = nn.ModuleList([
            ResidualAttentionFusion(
                source_channels=block_output_channels[:block_idx],
                target_channels=block_input_channels[block_idx],
            )
            for block_idx in range(1, len(self.encoder_blocks))
        ])

        final_channels = filts[-1][-1]
        self.pos_S = nn.Parameter(torch.randn(1, 23, final_channels))
        self.master1 = nn.Parameter(torch.randn(1, 1, gat_dims[0]))
        self.master2 = nn.Parameter(torch.randn(1, 1, gat_dims[0]))

        self.GAT_layer_S = GraphAttentionLayer(final_channels,
                                               gat_dims[0],
                                               temperature=temperatures[0])
        self.GAT_layer_T = GraphAttentionLayer(final_channels,
                                               gat_dims[0],
                                               temperature=temperatures[1])

        self.HtrgGAT_layer_ST11 = HtrgGraphAttentionLayer(
            gat_dims[0], gat_dims[1], temperature=temperatures[2])
        self.HtrgGAT_layer_ST12 = HtrgGraphAttentionLayer(
            gat_dims[1], gat_dims[1], temperature=temperatures[2])

        self.HtrgGAT_layer_ST21 = HtrgGraphAttentionLayer(
            gat_dims[0], gat_dims[1], temperature=temperatures[2])

        self.HtrgGAT_layer_ST22 = HtrgGraphAttentionLayer(
            gat_dims[1], gat_dims[1], temperature=temperatures[2])

        self.pool_S = GraphPool(pool_ratios[0], gat_dims[0], 0.3)
        self.pool_T = GraphPool(pool_ratios[1], gat_dims[0], 0.3)
        self.pool_hS1 = GraphPool(pool_ratios[2], gat_dims[1], 0.3)
        self.pool_hT1 = GraphPool(pool_ratios[2], gat_dims[1], 0.3)

        self.pool_hS2 = GraphPool(pool_ratios[2], gat_dims[1], 0.3)
        self.pool_hT2 = GraphPool(pool_ratios[2], gat_dims[1], 0.3)

        self.out_layer = nn.Linear(5 * gat_dims[1], 2)

    def _forward_encoder(self, x):
        residuals = []

        out = self.encoder_blocks[0](x)
        residuals.append(out)

        for block_idx, block in enumerate(self.encoder_blocks[1:], start=1):
            fused_input = self.residual_attention[block_idx - 1](residuals)
            out = block(fused_input)
            residuals.append(out)

        return residuals[-1]

    def forward(self, x, Freq_aug=False):

        x = x.unsqueeze(1)
        x = self.conv_time(x, mask=Freq_aug)
        x = x.unsqueeze(dim=1)
        x = F.max_pool2d(torch.abs(x), (3, 3))
        x = self.first_bn(x)
        x = self.selu(x)

        e = self._forward_encoder(x)

        e_S, _ = torch.max(torch.abs(e), dim=3)
        e_S = e_S.transpose(1, 2) + self.pos_S

        gat_S = self.GAT_layer_S(e_S)
        out_S = self.pool_S(gat_S)

        e_T, _ = torch.max(torch.abs(e), dim=2)
        e_T = e_T.transpose(1, 2)

        gat_T = self.GAT_layer_T(e_T)
        out_T = self.pool_T(gat_T)

        master1 = self.master1.expand(x.size(0), -1, -1)
        master2 = self.master2.expand(x.size(0), -1, -1)

        out_T1, out_S1, master1 = self.HtrgGAT_layer_ST11(
            out_T, out_S, master=self.master1)

        out_S1 = self.pool_hS1(out_S1)
        out_T1 = self.pool_hT1(out_T1)

        out_T_aug, out_S_aug, master_aug = self.HtrgGAT_layer_ST12(
            out_T1, out_S1, master=master1)
        out_T1 = out_T1 + out_T_aug
        out_S1 = out_S1 + out_S_aug
        master1 = master1 + master_aug

        out_T2, out_S2, master2 = self.HtrgGAT_layer_ST21(
            out_T, out_S, master=self.master2)
        out_S2 = self.pool_hS2(out_S2)
        out_T2 = self.pool_hT2(out_T2)

        out_T_aug, out_S_aug, master_aug = self.HtrgGAT_layer_ST22(
            out_T2, out_S2, master=master2)
        out_T2 = out_T2 + out_T_aug
        out_S2 = out_S2 + out_S_aug
        master2 = master2 + master_aug

        out_T1 = self.drop_way(out_T1)
        out_T2 = self.drop_way(out_T2)
        out_S1 = self.drop_way(out_S1)
        out_S2 = self.drop_way(out_S2)
        master1 = self.drop_way(master1)
        master2 = self.drop_way(master2)

        out_T = torch.max(out_T1, out_T2)
        out_S = torch.max(out_S1, out_S2)
        master = torch.max(master1, master2)

        T_max, _ = torch.max(torch.abs(out_T), dim=1)
        T_avg = torch.mean(out_T, dim=1)

        S_max, _ = torch.max(torch.abs(out_S), dim=1)
        S_avg = torch.mean(out_S, dim=1)

        last_hidden = torch.cat(
            [T_max, T_avg, S_max, S_avg, master.squeeze(1)], dim=1)

        last_hidden = self.drop(last_hidden)
        output = self.out_layer(last_hidden)

        return last_hidden, output
