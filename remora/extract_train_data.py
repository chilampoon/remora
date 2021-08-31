from taiyaki.mapped_signal_files import MappedSignalReader
from remora.chunk_selection import (
    sample_chunks_bybase,
    sample_chunks_bychunksize,
)


def get_train_set(train_path, mod_offset):
    """
    Args:
        train_path: path to a hdf5 file generated by extract_toy_dataset

    Returns:
        sigs: list of signal chunks
        labels: list of mod/unmod labels for the corresponding chunks
        refs: list of reference sequences for each chunk
        base_locs: location for each base in the corersponing chunk
    """
    mod_training_msf = MappedSignalReader(train_path)
    alphabet_info = mod_training_msf.get_alphabet_information()
    sigs = []
    labels = []
    refs = []
    base_locs = []

    for read in mod_training_msf:
        sigs.append(read.get_current(read.get_mapped_dacs_region()))
        ref = "".join(
            alphabet_info.collapse_alphabet[b] for b in read.Reference
        )
        refs.append(ref)
        base_locs.append(read.Ref_to_signal - read.Ref_to_signal[0])
        is_mod = read.Reference[mod_offset] == 1
        labels.append(is_mod)
    return sigs, labels, refs, base_locs


def get_centred_train_set(
    train_path,
    number_to_sample,
    mod,
    bases_below=5,
    bases_above=5,
    chunk_size_below=50,
    chunk_size_above=50,
    mod_offset=20,
    evenchunks=False,
):
    """
    Args:
        train_path: path to a hdf5 file generated by extract_toy_dataset
        number_to_sample: size of returned dataset in number of instances
        bases_below: choose number of bases before modbase in sequence to include
        bases_above: choose number of bases after modbase in sequence to include
        mod_offset: index of modbase in reference
        evenchunks: return all chunks evenly sized TODO include a padding option

    Returns:
        sigs: list of signal chunks
        labels: list of mod/unmod labels for the corresponding chunks
        refs: list of reference sequences for each chunk
        base_locs: location for each base in the corersponing chunk
    """

    if evenchunks:

        (
            sigs,
            labels,
            refs,
            base_locs,
            read_ids,
            positions,
        ) = sample_chunks_bychunksize(
            read_data_path=train_path,
            number_to_sample=number_to_sample,
            mod=mod,
            chunk_size_below=chunk_size_below,
            chunk_size_above=chunk_size_above,
            mod_offset=mod_offset,
        )
        (
            control_sigs,
            control_labels,
            control_refs,
            control_base_locs,
            control_read_ids,
            control_positions,
        ) = sample_chunks_bychunksize(
            read_data_path=train_path,
            number_to_sample=number_to_sample,
            mod=mod,
            chunk_size_below=chunk_size_below,
            chunk_size_above=chunk_size_above,
            mod_offset=mod_offset + 10,
        )

    else:

        (
            sigs,
            labels,
            refs,
            base_locs,
            read_ids,
            positions,
        ) = sample_chunks_bybase(
            read_data_path=train_path,
            number_to_sample=number_to_sample,
            bases_below=bases_below,
            bases_above=bases_above,
            mod_offset=mod_offset,
            mod=mod,
        )

        (
            control_sigs,
            control_labels,
            control_refs,
            control_base_locs,
            control_read_ids,
            control_positions,
        ) = sample_chunks_bybase(
            read_data_path=train_path,
            number_to_sample=number_to_sample,
            bases_below=bases_below,
            bases_above=bases_above,
            mod_offset=mod_offset + 10,
            mod=mod,
        )

    out_sigs = sigs + control_sigs
    out_labels = labels + control_labels
    out_refs = refs + control_refs
    out_base_locs = base_locs + control_base_locs
    out_read_ids = read_ids + control_read_ids
    out_positions = positions + control_positions

    out_labels = [int(x == True) for x in out_labels]

    return (
        out_sigs,
        out_labels,
        out_refs,
        out_base_locs,
        out_read_ids,
        out_positions,
    )

    # TODO: write methods and robust API to train prediction model (for is_mod)
    # from sig and ref.
    # ref is fixed length (MOD_OFFSET * 2 + 1)
    # signal in this case is assigned by megalodon (so essentially the coarse
    # mapping from tombo2)
    # The exact mapping from reference bases to signal is found in base_locs.
    # base_locs need not be used in prediction, but may be used if desired.
