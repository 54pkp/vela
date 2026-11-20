#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-only
"""Export the AMD 1080p FSR 4.1.2 Lite network for Vela's Hexagon tensor ABI."""

import argparse
import hashlib
import json
from pathlib import Path

import numpy as np
import onnx
from onnx import TensorProto, helper, numpy_helper


# Initializer layout and integer epilogues cross-checked against the MIT
# fsr4-native-macos implementation at 6204fd5b89c525d6e67798f3e8d344f59e7a9adb.
# https://github.com/UzenUPoZiTiV4ik/fsr4-native-macos/blob/6204fd5b89c525d6e67798f3e8d344f59e7a9adb/tools/fsr412/native_model.py
WEIGHTS_SHA256 = "4b9898da719dc2dca5dc45fd71dec5f80bdb9886a580fe3038af59efe637d55e"
INPUT_NAME = "x"
OUTPUT_NAMES = ("p3u_o", "p1f_o")


class Network:
    def __init__(self, weights):
        self.weights = weights
        self.nodes = []
        self.initializers = {}
        self.init("unit", np.float32(1))
        self.init("u8_zero", np.uint8(128))
        self.init("s8_zero", np.int8(0))

    def init(self, name, value):
        self.initializers[name] = numpy_helper.from_array(np.asarray(value), name)
        return name

    def node(self, kind, name, *inputs, **attributes):
        self.nodes.append(helper.make_node(kind, inputs, [name], name=name, **attributes))
        return name

    def coefficients(self, weight, bias, cin, cout, kernel=1, phases=1):
        taps = kernel * kernel * phases
        w = np.frombuffer(self.weights, np.int8, count=taps * cin * cout, offset=weight)
        w = w.reshape(taps, cout, cin).transpose(1, 2, 0)
        if phases != 1:
            # Four consecutive 16-channel phases ordered by (y mod 2, x mod 2).
            w = w.transpose(2, 0, 1).reshape(phases * cout, cin)
        out = cout * phases
        b = np.frombuffer(self.weights, "<i4", count=cout, offset=bias)
        return w.reshape(out, cin, kernel, kernel), np.tile(b, phases)

    def conv(self, x, name, coeffs, shift, stride=1, relu=False):
        weight, bias = coeffs
        kernel = weight.shape[2]
        pad = 1 if kernel == 3 else 0
        scale = f"div{1 << shift}"
        if scale not in self.initializers:
            self.init(scale, np.float32(2 ** -shift))
        out = self.node(
            "QLinearConv", f"{name}_conv" if relu else name,
            x, "unit", "u8_zero", self.init(f"{name}_w", weight), scale, "s8_zero",
            "unit", "u8_zero", self.init(f"{name}_b", bias),
            kernel_shape=[kernel, kernel], strides=[stride, stride], pads=[pad] * 4,
        )
        if relu:
            # Quantization is monotonic and exact at zero, so this is the
            # same as clamping the signed accumulator before the right shift.
            real = self.node("DequantizeLinear", f"{name}_real", out, "unit", "u8_zero")
            positive = self.node("Relu", f"{name}_positive", real)
            return self.node("QuantizeLinear", name, positive, "unit", "u8_zero")
        return out

    def channels(self, x, name, begin, end):
        if "channel_axis" not in self.initializers:
            self.init("channel_axis", np.array([1], dtype=np.int64))
        return self.node("Slice", name, x,
                         self.init(f"{name}_begin", np.array([begin], dtype=np.int64)),
                         self.init(f"{name}_end", np.array([end], dtype=np.int64)), "channel_axis")

    def residual(self, expanded, skip, name, coeffs, shift, gain):
        w, bias = coeffs
        cout = w.shape[0]
        # Keep the skip in the same INT32 accumulation as the learned dot
        # product. Apply the division, round-to-even and saturation only once.
        # Large gains split across copies so every coefficient stays signed 8-bit.
        gains = [127] * (gain // 127)
        if gain % 127:
            gains.append(gain % 127)
        identity = np.eye(cout, dtype=np.int8).reshape(cout, cout, 1, 1)
        joined = self.node("Concat", f"{name}_concat", expanded, *([skip] * len(gains)), axis=1)
        return self.conv(joined, name, (np.concatenate([w, *(identity * g for g in gains)], axis=1), bias), shift)

    def split(self, x, name, coeffs, shifts, stride=1, skip=None, gains=None):
        w, b = coeffs
        count = w.shape[0]
        outputs = []
        for i, (begin, end) in enumerate(((0, count // 2), (count // 2, count))):
            label = f"{name}_{i}"
            coeff = (w[begin:end], b[begin:end])
            if skip is None:
                outputs.append(self.conv(x, label, coeff, shifts[i], stride))
            else:
                residual = self.channels(skip, f"{label}_skip", begin, end)
                outputs.append(self.residual(x, residual, label, coeff, shifts[i], gains[i]))
        return self.node("Concat", name, *outputs, axis=1)

    def fnb(self, x, name, offsets, shifts, gains):
        (w0, b0), (w1, b1), (w2, b2) = offsets
        first = self.channels(x, f"{name}_head", 0, 16)
        bypass = self.channels(x, f"{name}_bypass", 16, 32)
        first = self.conv(first, f"{name}_filter", self.coefficients(w0, b0, 16, 16, 3), 8)
        merged = self.node("Concat", f"{name}_features", first, bypass, axis=1)
        expanded = self.conv(merged, f"{name}_expand", self.coefficients(w1, b1, 32, 64), shifts[0], relu=True)
        return self.split(expanded, name, self.coefficients(w2, b2, 64, 32), shifts[1:], skip=x, gains=gains)

    def build(self, height, width):
        first = self.conv(INPUT_NAME, "p1_filter", self.coefficients(1152, 3456, 16, 16, 3), 7)
        expanded = self.conv(first, "p1_expand", self.coefficients(3584, 4096, 16, 32), 9, relu=True)
        p1 = self.residual(expanded, INPUT_NAME, "p1", self.coefficients(4224, 4736, 32, 16), 6, 32)
        down = self.split(p1, "down", self.coefficients(4864, 6912, 16, 32, 2), (6, 7), stride=2)
        p2 = self.fnb(down, "p2", ((7040, 9344), (9472, 11520), (11776, 13824)), (8, 6, 7), (32, 64))
        p3 = self.fnb(p2, "p3", ((13952, 16256), (16384, 18432), (18688, 20736)), (7, 6, 6), (64, 128))

        # The shader's final residual is added before round/saturation. Send
        # the complete result unshuffled as out0 and a neutral out1. Vela's
        # existing unpack shader computes sat(pixelshuffle(out0) + out1).
        p1_real = self.node("DequantizeLinear", "p1_real", p1, "unit", "u8_zero")
        phases = self.node("SpaceToDepth", "p1_phases_real", p1_real, blocksize=2)
        skip = self.node("QuantizeLinear", "p1_phases", phases, "unit", "u8_zero")
        self.residual(p3, skip, OUTPUT_NAMES[0], self.coefficients(20864, 22912, 32, 16, phases=4), 8, 256)
        x_real = self.node("DequantizeLinear", "x_real", INPUT_NAME, "unit", "u8_zero")
        neutral = self.node("Sub", "neutral", x_real, x_real)
        self.node("QuantizeLinear", OUTPUT_NAMES[1], neutral, "unit", "u8_zero")

        def tensor(name, shape):
            return helper.make_tensor_value_info(name, TensorProto.UINT8, shape)

        graph = helper.make_graph(self.nodes, "fsr412_lite_1080p",
            [tensor(INPUT_NAME, [1, 16, height, width])],
            [tensor(OUTPUT_NAMES[0], [1, 64, height // 2, width // 2]),
             tensor(OUTPUT_NAMES[1], [1, 16, height, width])],
            list(self.initializers.values()))
        model = helper.make_model(graph, opset_imports=[helper.make_opsetid("", 13)], ir_version=8)
        onnx.checker.check_model(model, full_check=True)
        return model


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--weights", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--qairt-encodings", type=Path,
                        help="emit a QAIRT converter model with fixed quantizer overrides")
    parser.add_argument("--size", type=int, nargs=2, default=(960, 540), metavar=("WIDTH", "HEIGHT"),
                        help="smaller even dimensions are for CPU contract checks only")
    args = parser.parse_args()
    width, height = args.size
    if not (2 <= width <= 960 and 2 <= height <= 540 and width % 2 == height % 2 == 0):
        parser.error("use positive even dimensions up to 960×540")
    weights = args.weights.read_bytes()
    if hashlib.sha256(weights).hexdigest() != WEIGHTS_SHA256:
        parser.error("wrong Lite initializer SHA-256")
    model = Network(weights).build(height, width)
    if args.qairt_encodings:
        model, encodings = qairt_model(model)
        with args.qairt_encodings.open("x", encoding="utf-8") as file:
            json.dump(encodings, file, indent=2)
    with args.output.open("xb") as file:
        file.write(model.SerializeToString())


def qairt_model(reference):
    """Lower QLinearConv to float import ops, retaining the exact W8A8 grid."""

    def encoding(scale):
        return [{"bitwidth": 8, "is_symmetric": "false", "scale": scale,
                 "offset": -128, "min": -128 * scale, "max": 127 * scale}]

    tensors = {item.name: numpy_helper.to_array(item) for item in reference.graph.initializer}
    init, nodes, aliases = {}, [], {}
    activations = {INPUT_NAME: encoding(1.0)}
    params = {}
    output_names = set(OUTPUT_NAMES)
    for node in reference.graph.node:
        name = node.output[0]
        sources = [aliases.get(arg, arg) for arg in node.input]
        if node.op_type in {"DequantizeLinear", "QuantizeLinear"}:
            if name not in output_names:
                aliases[name] = sources[0]
                continue
            sources = sources[:1]
            kind = "Identity"
        elif node.op_type == "QLinearConv":
            x, _, _, w, scale_name, _, _, _, bias = sources
            scale = float(tensors[scale_name])
            for coefficient in (w, bias):
                init[coefficient] = numpy_helper.from_array(tensors[coefficient].astype(np.float32) * scale, coefficient)
            params[w] = encoding(scale)
            sources = [x, w, bias]
            kind = "Conv"
        else:
            kind = node.op_type
            for arg in sources:
                if arg in tensors:
                    init[arg] = numpy_helper.from_array(tensors[arg], arg)

        attributes = {attr.name: helper.get_attribute_value(attr) for attr in node.attribute}
        nodes.append(helper.make_node(kind, sources, [name], name=name, **attributes))
        activations[name] = encoding(1.0)

    def as_float(tensor):
        shape = [dim.dim_value for dim in tensor.type.tensor_type.shape.dim]
        return helper.make_tensor_value_info(tensor.name, TensorProto.FLOAT, shape)

    graph = helper.make_graph(nodes, reference.graph.name, [as_float(t) for t in reference.graph.input],
                              [as_float(t) for t in reference.graph.output], list(init.values()))
    model = helper.make_model(graph, opset_imports=[helper.make_opsetid("", 13)], ir_version=8)
    onnx.checker.check_model(model, full_check=True)
    return model, {"version": "0.6.1", "activation_encodings": activations, "param_encodings": params}


if __name__ == "__main__":
    main()
