import atexit
import os

import numpy as np
import pandas as pd
from tqdm import tqdm

from remora import constants, log, RemoraError, encoded_kmers
from remora.data_chunks import RemoraDataset, RemoraRead
from remora.util import (
    softmax_axis1,
    Motif,
    validate_mod_bases,
    get_can_converter,
)
from remora.model_util import load_onnx_model

LOGGER = log.get_logger()


class resultsWriter:
    def __init__(self, output_path):
        self.sep = "\t"
        self.out_fp = open(output_path, "w")
        df = pd.DataFrame(
            columns=[
                "read_id",
                "read_pos",
                "label",
                "class_pred",
                "class_probs",
            ]
        )
        df.to_csv(self.out_fp, sep=self.sep, index=False)

    def write_results(self, output, labels, read_pos, read_id):
        class_preds = output.argmax(axis=1)
        str_probs = [",".join(map(str, r)) for r in softmax_axis1(output)]
        pd.DataFrame(
            {
                "read_id": read_id,
                "read_pos": read_pos,
                "label": labels,
                "class_pred": class_preds,
                "class_probs": str_probs,
            }
        ).to_csv(self.out_fp, header=False, index=False, sep=self.sep)

    def close(self):
        self.out_fp.close()


def call_read_mods(
    read,
    model,
    model_metadata,
    batch_size=constants.DEFAULT_BATCH_SIZE,
    focus_offset=None,
):
    """Call modified bases on a read.

    Args:
        read (RemoraRead): Read to be called
        model (ort.InferenceSession): Inference model
            (see remora.model_util.load_onnx_model)
        model_metadata (ort.InferenceSession): Inference model metadata
        batch_size (int): Number of chunks to call per-batch
        focus_offset (int): Specific base to call within read
            Default: Use motif from model

    Returns:
        3-tuple containing:
          1. Modified base predictions (dim: num_calls, num_mods + 1)
          2. Labels for each base (-1 if labels not provided)
          3. List of positions within the read
    """
    read_outputs, all_read_data, read_labels = [], [], []

    motif = Motif(*model_metadata["motif"])
    bb, ab = model_metadata["kmer_context_bases"]
    if focus_offset is not None:
        motif_hits = focus_offset
    elif motif.any_context:
        motif_hits = np.arange(
            motif.focus_pos,
            read.can_seq.size - motif.num_bases_after_focus,
        )
    else:
        motif_hits = np.fromiter(read.iter_motif_hits(motif), int)
    chunks = list(
        read.iter_chunks(
            motif_hits,
            model_metadata["chunk_context"],
            model_metadata["kmer_context_bases"],
            model_metadata["base_pred"],
        )
    )
    if len(chunks) == 0:
        return (
            np.empty((0, 2), dtype=np.float32),
            np.empty(0, dtype=np.long),
            [],
        )
    read_dataset = RemoraDataset.allocate_empty_chunks(
        num_chunks=len(motif_hits),
        chunk_context=model_metadata["chunk_context"],
        max_seq_len=max(c.seq_len for c in chunks),
        kmer_context_bases=model_metadata["kmer_context_bases"],
        base_pred=model_metadata["base_pred"],
        mod_bases=model_metadata["mod_bases"],
        mod_long_names=model_metadata["mod_long_names"],
        motif=motif.to_tuple(),
        store_read_data=True,
        batch_size=batch_size,
        shuffle_on_iter=False,
        drop_last=False,
    )
    for chunk in chunks:
        read_dataset.add_chunk(chunk)
    read_dataset.set_nbatches()
    for (sigs, seqs, seq_maps, seq_lens), labels, read_data in read_dataset:
        enc_kmers = encoded_kmers.compute_encoded_kmer_batch(
            bb, ab, seqs, seq_maps, seq_lens
        )
        read_outputs.append(model.run([], {"sig": sigs, "seq": enc_kmers})[0])
        read_labels.append(labels)
        all_read_data.extend(read_data)
    read_outputs = np.concatenate(read_outputs, axis=0)
    read_labels = np.concatenate(read_labels)
    return read_outputs, read_labels, list(zip(*all_read_data))[1]


def infer(
    input_msf,
    out_path,
    onnx_model_path,
    batch_size,
    device,
    focus_offset,
):
    LOGGER.info("Performing Remora inference")
    alphabet_info = input_msf.get_alphabet_information()
    alphabet, collapse_alphabet = (
        alphabet_info.alphabet,
        alphabet_info.collapse_alphabet,
    )

    if focus_offset is not None:
        focus_offset = np.array([focus_offset])

    rw = resultsWriter(os.path.join(out_path, "results.tsv"))
    atexit.register(rw.close)

    LOGGER.info("Loading model")
    model, model_metadata = load_onnx_model(onnx_model_path, device)

    if model_metadata["base_pred"]:
        if alphabet != "ACGT":
            raise ValueError(
                "Base prediction is not compatible with modified base "
                "training data. It requires a canonical alphabet."
            )
        label_conv = get_can_converter(alphabet, collapse_alphabet)
    else:
        try:
            motif = Motif(*model_metadata["motif"])
            label_conv = validate_mod_bases(
                model_metadata["mod_bases"], motif, alphabet, collapse_alphabet
            )
        except RemoraError:
            label_conv = None

    can_conv = get_can_converter(
        alphabet_info.alphabet, alphabet_info.collapse_alphabet
    )
    num_reads = len(input_msf.get_read_ids())
    for read in tqdm(input_msf, smoothing=0, total=num_reads, unit="reads"):
        try:
            read = RemoraRead.from_taiyaki_read(read, can_conv, label_conv)
        except RemoraError:
            # TODO log these failed reads to track down errors
            continue
        output, labels, read_pos = call_read_mods(
            read,
            model,
            model_metadata,
            batch_size,
            focus_offset,
        )
        rw.write_results(output, labels, read_pos, read.read_id)


if __name__ == "__main__":
    NotImplementedError("This is a module.")