#!/usr/bin/env python3
"""Unsloth QLoRA fine-tune on a chat-format SFT JSONL — runs in the box's training venv.

Reads ``{"messages":[...]}`` JSONL, fine-tunes the bnb-4bit base with a LoRA adapter, saves
the adapter (+ tokenizer), and prints a BEFORE/AFTER generation on a held-out prompt so the
effect is visible. GPU + a provisioned training venv (torch + unsloth + trl) required.

Config via env:
  WF_FT_DATA        the training JSONL (REQUIRED)
  WF_FT_BASE        bnb-4bit base (default unsloth/Qwen2.5-7B-Instruct-bnb-4bit)
  WF_FT_OUT         adapter output dir (default ~/.wf-finetune/out/adapter)
  WF_FT_SEQ         max sequence length (default 2048)
  WF_FT_STEPS       max train steps (default 30 — small for a first proof)
  WF_FT_LORA_R      LoRA rank/alpha (default 16)
  WF_FT_BATCH       per-device batch (default 1)
  WF_FT_GRAD_ACCUM  gradient accumulation (default 4)
  WF_FT_LR          learning rate (default 2e-4)
  WF_FT_SEED        random seed (default 3407)

Optional private overrides: if ``core/private/finetune.yaml`` exists next to this checkout,
its ``out`` key replaces the default output dir and its ``legacy_env_prefix`` key names an
older env-var prefix still honoured as a fallback (e.g. ``<PREFIX>FT_DATA``). Absent that
file, the generic defaults above apply.

The chat template is the base tokenizer's native one (Qwen2.5-Instruct ships it).
"""

from __future__ import annotations

import os
import sys
import time

_PRIVATE_CFG_PATH = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "core", "private", "finetune.yaml"
)


def _load_private_cfg() -> dict:
    """Flat ``key: value`` reader for the optional private config (stdlib only)."""
    cfg: dict = {}
    try:
        with open(_PRIVATE_CFG_PATH, encoding="utf-8") as fh:
            text = fh.read()
    except OSError:
        return cfg
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or ":" not in line:
            continue
        key, val = line.split(":", 1)
        cfg[key.strip()] = val.strip().strip('"').strip("'")
    return cfg


_CFG = _load_private_cfg()


def _env(name: str, default: str) -> str:
    """``name`` (a WF_* var) wins; else the private legacy-prefixed twin; else default."""
    if name in os.environ:
        return os.environ[name]
    legacy = _CFG.get("legacy_env_prefix", "")
    if legacy and name.startswith("WF_") and legacy + name[3:] in os.environ:
        return os.environ[legacy + name[3:]]
    return default


_HELD_OUT = "Design an empty state for a brand-new team chat workspace that has no messages yet."


def main() -> int:
    data = _env("WF_FT_DATA", "")
    if not data or not os.path.isfile(data):
        print(f"FATAL: WF_FT_DATA is not a file: {data!r}")
        return 2
    base = _env("WF_FT_BASE", "unsloth/Qwen2.5-7B-Instruct-bnb-4bit")
    out_dir = os.path.expanduser(_env("WF_FT_OUT", _CFG.get("out", "~/.wf-finetune/out/adapter")))
    max_seq = int(_env("WF_FT_SEQ", "2048"))
    max_steps = int(_env("WF_FT_STEPS", "30"))
    lora_r = int(_env("WF_FT_LORA_R", "16"))
    bsz = int(_env("WF_FT_BATCH", "1"))
    grad_accum = int(_env("WF_FT_GRAD_ACCUM", "4"))
    lr = float(_env("WF_FT_LR", "2e-4"))
    seed = int(_env("WF_FT_SEED", "3407"))
    os.makedirs(out_dir, exist_ok=True)

    print(
        f"=== finetune_qlora base={base} data={data} steps={max_steps} "
        f"r={lora_r} seq={max_seq} batch={bsz}x{grad_accum} ==="
    )
    t0 = time.time()

    from datasets import disable_caching, load_dataset
    from trl import SFTConfig, SFTTrainer
    from unsloth import FastLanguageModel, is_bfloat16_supported

    from _eos_alias import TokenIdAlias

    # trl's "Adding EOS"/"Tokenizing" dataset maps fan out through datasets + the multiprocess
    # fork whenever dataset_num_proc is an int (this datasets version pools even at 1), and the
    # worker task pickles the Unsloth tokenizer via dill's ForkingPickler — which fails on an
    # unpicklable torch ConfigModuleInstance reachable from it. trl passes num_proc straight
    # through to dataset.map (verified live), so SFTConfig(dataset_num_proc=None) below forces
    # in-process maps and nothing is pickled. TokenIdAlias is additionally kept in an importable
    # module so the tokenizer stays by-reference-picklable for any other path (e.g. dataloader
    # workers). disable_caching() skips datasets' fingerprint dill-dump.
    disable_caching()

    model, tokenizer = FastLanguageModel.from_pretrained(
        model_name=base, max_seq_length=max_seq, load_in_4bit=True, dtype=None
    )
    model = FastLanguageModel.get_peft_model(
        model,
        r=lora_r,
        lora_alpha=lora_r,
        lora_dropout=0.0,
        target_modules=["q_proj", "k_proj", "v_proj", "o_proj", "gate_proj", "up_proj", "down_proj"],
        use_gradient_checkpointing="unsloth",
        random_state=seed,
    )
    # EOS hardening. On this stack (unsloth 2026.6.9 / trl 0.24 / transformers 5.5.0) trl's
    # SFTTrainer validates `args.eos_token` against the vocab, and unsloth's trl patch
    # OVERWRITES SFTConfig.eos_token with the literal placeholder `<EOS_TOKEN>` from inside
    # SFTTrainer.__init__. Verified live: the tokenizer's real eos is `<|im_end|>` and we pass
    # eos_token=`<|im_end|>` to SFTConfig, yet the trainer still sees `<EOS_TOKEN>` (not in
    # vocab) and hard-errors — so passing the arg can't win, and there's no hook inside __init__.
    # Fix at the only interception point that works: trl's check is
    # `convert_tokens_to_ids(args.eos_token)`, so alias `<EOS_TOKEN>` to the real eos id on the
    # tokenizer. The validation then passes AND trl's self.eos_token_id is the correct id (trl
    # uses the int id downstream, never the string — no `<EOS_TOKEN>` text leaks into the data).
    # Belt-and-suspenders: also repair a corrupted tokenizer.eos_token and pass the real eos to
    # SFTConfig (both harmless no-ops on a healthy load).
    def _in_vocab(tok, t) -> bool:
        return bool(t) and t != "<EOS_TOKEN>" and tok.convert_tokens_to_ids(t) is not None

    eos_token = tokenizer.eos_token
    if not _in_vocab(tokenizer, eos_token):
        eos_token = next(
            (c for c in ("<|im_end|>", "<|endoftext|>") if tokenizer.convert_tokens_to_ids(c) is not None),
            eos_token,
        )
        tokenizer.eos_token = eos_token
        print(f"repaired corrupted tokenizer.eos_token -> {eos_token!r}")
    if not _in_vocab(tokenizer, tokenizer.pad_token):
        tokenizer.pad_token = eos_token

    # unsloth injects bare placeholders (`<EOS_TOKEN>`, `<PAD_TOKEN>`, and `<BOS_TOKEN>` if
    # present) into SFTConfig's special-token fields, and trl validates each via
    # convert_tokens_to_ids — eos tripped first (line 632), then pad (line 754). Map every
    # placeholder we have a real token for to its real id so the trainer constructs with the
    # correct ids (trl stores the int id, never the placeholder string). TokenIdAlias lives in
    # an importable module so it pickles cleanly through trl's multiprocess tokenization map.
    _alias_ids = {}
    if tokenizer.eos_token_id is not None:
        _alias_ids["<EOS_TOKEN>"] = tokenizer.eos_token_id
    if tokenizer.pad_token_id is not None:
        _alias_ids["<PAD_TOKEN>"] = tokenizer.pad_token_id
    if tokenizer.bos_token_id is not None:
        _alias_ids["<BOS_TOKEN>"] = tokenizer.bos_token_id
    tokenizer.convert_tokens_to_ids = TokenIdAlias(tokenizer, _alias_ids)
    print(f"eos_token={eos_token!r} pad_token={tokenizer.pad_token!r} aliased={_alias_ids}")

    def generate(prompt: str) -> str:
        FastLanguageModel.for_inference(model)
        ids = tokenizer.apply_chat_template(
            [{"role": "user", "content": prompt}],
            tokenize=True,
            add_generation_prompt=True,
            return_tensors="pt",
        ).to("cuda")
        out = model.generate(input_ids=ids, max_new_tokens=160, use_cache=True, temperature=0.7)
        return tokenizer.decode(out[0][ids.shape[1]:], skip_special_tokens=True)

    print("--- BEFORE (base model) ---")
    print(generate(_HELD_OUT)[:600])

    dataset = load_dataset("json", data_files=data, split="train")
    print(f"loaded {len(dataset)} training records")

    # Pre-tokenize HERE, in our own in-process dataset.map (default num_proc=None — unsloth only
    # patches SFTConfig/SFTTrainer, not our direct map call), producing `input_ids`. trl 0.24's
    # _prepare_dataset then sees is_processed = "input_ids" in columns == True and SKIPS both its
    # "Adding EOS" and "Tokenizing" maps — the maps that otherwise fan out via unsloth's forced
    # num_proc (None→11, any int→pooled on this datasets version) and crash pickling the Unsloth
    # tokenizer ("cannot pickle ConfigModuleInstance"). The chat template already terminates each
    # turn with the EOS (<|im_end|>), so add_special_tokens=False avoids double special tokens.
    def to_input_ids(batch: dict) -> dict:
        texts = [
            tokenizer.apply_chat_template(m, tokenize=False, add_generation_prompt=False)
            for m in batch["messages"]
        ]
        enc = tokenizer(texts, truncation=True, max_length=max_seq, add_special_tokens=False)
        return {"input_ids": enc["input_ids"], "attention_mask": enc["attention_mask"]}

    dataset = dataset.map(to_input_ids, batched=True, remove_columns=list(dataset.column_names))
    print(f"pre-tokenized {len(dataset)} records in-process; columns={dataset.column_names}")

    FastLanguageModel.for_training(model)
    trainer = SFTTrainer(
        model=model,
        train_dataset=dataset,
        processing_class=tokenizer,
        args=SFTConfig(
            eos_token=eos_token,
            dataset_num_proc=None,
            max_length=max_seq,
            per_device_train_batch_size=bsz,
            gradient_accumulation_steps=grad_accum,
            warmup_steps=5,
            max_steps=max_steps,
            learning_rate=lr,
            fp16=not is_bfloat16_supported(),
            bf16=is_bfloat16_supported(),
            logging_steps=1,
            optim="adamw_8bit",
            weight_decay=0.01,
            lr_scheduler_type="linear",
            seed=seed,
            output_dir=os.path.join(out_dir, "_trainer"),
            report_to="none",
        ),
    )
    # trl 0.24's compute_loss computes per-token entropy AND token-accuracy from outputs.logits
    # purely for logging. Unsloth's memory-efficient training forward does NOT materialize real
    # logits (outputs.logits is a stub, not a tensor — "'function' object is not subscriptable"
    # at logits.shape), so both metric blocks crash on the first step. trl gates BOTH blocks
    # behind `if not self.args.use_liger_kernel` ("liger doesn't return logits" — the same
    # no-logits situation), and the loss itself comes from super().compute_loss regardless. So we
    # want the *flag* True (to skip the logits-only metric blocks) but NOT the Liger kernel
    # (Unsloth owns the kernels, and liger-kernel isn't installed). transformers re-applies Liger
    # at train() start when the flag is True, raising ImportError — so neutralize that single
    # apply_liger_kernel call to a no-op, then enable the flag.
    import transformers.trainer as _hf_trainer

    _hf_trainer.apply_liger_kernel = lambda *a, **k: None
    trainer.args.use_liger_kernel = True
    result = trainer.train()
    loss = getattr(result, "training_loss", float("nan"))
    print(f"--- trained {max_steps} steps in {(time.time()-t0)/60:.1f} min; final loss ~{loss:.4f} ---")

    print("--- AFTER (fine-tuned) ---")
    print(generate(_HELD_OUT)[:600])

    model.save_pretrained(out_dir)
    tokenizer.save_pretrained(out_dir)
    files = sorted(os.listdir(out_dir))
    print(f"=== saved adapter → {out_dir} ({len(files)} files: {files[:8]}) ===")
    return 0


if __name__ == "__main__":
    sys.exit(main())
