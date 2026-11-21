// Licensed to the Apache Software Foundation (ASF) under one
// or more contributor license agreements.  See the NOTICE file
// distributed with this work for additional information
// regarding copyright ownership.  The ASF licenses this file
// to you under the Apache License, Version 2.0 (the
// "License"); you may not use this file except in compliance
// with the License.  You may obtain a copy of the License at
//
//   http://www.apache.org/licenses/LICENSE-2.0
//
// Unless required by applicable law or agreed to in writing,
// software distributed under the License is distributed on an
// "AS IS" BASIS, WITHOUT WARRANTIES OR CONDITIONS OF ANY
// KIND, either express or implied.  See the License for the
// specific language governing permissions and limitations
// under the License.

//! Expanding a mapped task into its instances, following ADR-0016.
//!
//! gust stands in for three components here: the scheduler counts the instances, the API server
//! works out which value each instance's arguments read, and the supervisor reads those values,
//! so the runtime only ever receives `literal` and `sequence` bindings.

use std::collections::{BTreeMap, BTreeSet};

use anyhow::{Context, Result, bail};
use serde_json::{Map, Value as Json, json};

use crate::dag::MappedSpec;

/// XCom values from `--input` for this Dag, by `(task_id, key)`.
pub type XComValues = BTreeMap<(String, String), Json>;

/// One expand argument.
#[derive(Debug)]
enum Arg {
    /// A literal list, or a literal dict's `[key, value]` pairs.
    Items(Vec<Json>),
    XCom {
        task_id: String,
        key: String,
    },
    /// `map()`: picks as the wrapped argument does; the runtime applies the callables.
    Map(Box<Arg>),
    Zip {
        args: Vec<Arg>,
        fillvalue: Option<Json>,
    },
    Concat(Vec<Arg>),
}

#[derive(Debug)]
enum ExpandInput {
    /// `expand()`: the cross product of every argument, the last varying fastest.
    DictOfLists {
        args: Vec<(String, Arg)>,
        lengths: Vec<usize>,
    },
    /// `expand_kwargs()`: one dict per instance.
    ListOfDicts(Arg),
}

/// Python's `{"__type": ..., "__var": ...}` encoding, if `value` uses it.
fn as_encoded(value: &Json) -> Option<(&str, &Json)> {
    let map = value.as_object()?;
    Some((map.get("__type")?.as_str()?, map.get("__var")?))
}

fn read_xcom<'x>(xcoms: &'x XComValues, task_id: &str, key: &str) -> Result<&'x Json> {
    xcoms
        .get(&(task_id.to_owned(), key.to_owned()))
        .with_context(|| {
            format!(
                "the expansion reads the XCom {task_id}/{key}; give it in --input under \"xcoms\""
            )
        })
}

/// The items a value expands into: a list's items, or an object's `[key, value]` pairs.
fn find_items(value: Json, what: &str) -> Result<Vec<Json>> {
    match value {
        Json::Array(items) => Ok(items),
        Json::Object(map) => Ok(map.into_iter().map(|(k, v)| json!([k, v])).collect()),
        other => bail!(
            "{what} is {other}, which is not a list or an object, so it cannot be expanded over"
        ),
    }
}

/// Decode a serialized literal into plain JSON. A reference to an upstream's whole output is
/// replaced with that output.
fn decode(value: &Json, xcoms: &XComValues) -> Result<Json> {
    if let Some((kind, var)) = as_encoded(value) {
        return match kind {
            "xcomref" => match parse_ref(var)? {
                Arg::XCom { task_id, key } => Ok(read_xcom(xcoms, &task_id, &key)?.clone()),
                _ => bail!("a map(), zip() or concat() result can only be expanded over"),
            },
            _ => decode(var, xcoms),
        };
    }
    match value {
        Json::Object(map) => map
            .iter()
            .map(|(k, v)| Ok((k.clone(), decode(v, xcoms)?)))
            .collect::<Result<Map<_, _>>>()
            .map(Json::Object),
        Json::Array(items) => items
            .iter()
            .map(|v| decode(v, xcoms))
            .collect::<Result<_>>()
            .map(Json::Array),
        other => Ok(other.clone()),
    }
}

/// Parse the body of an `xcomref`. Nested references are bare, without the `xcomref` wrapper.
fn parse_ref(var: &Json) -> Result<Arg> {
    let parse_args = |var: &Json| -> Result<Vec<Arg>> {
        let args = var
            .get("args")
            .and_then(Json::as_array)
            .context("a zip() or concat() reference has no \"args\"")?
            .iter()
            .map(parse_ref)
            .collect::<Result<Vec<_>>>()?;
        if args.iter().any(|a| matches!(a, Arg::Map(_))) {
            bail!("map() must be the outermost call of an expand argument");
        }
        Ok(args)
    };
    match var.get("type").and_then(Json::as_str).unwrap_or_default() {
        "" => Ok(Arg::XCom {
            task_id: var
                .get("task_id")
                .and_then(Json::as_str)
                .context("an XCom reference has no \"task_id\"")?
                .to_owned(),
            key: var
                .get("key")
                .and_then(Json::as_str)
                .unwrap_or("return_value")
                .to_owned(),
        }),
        "map" => Ok(Arg::Map(Box::new(parse_ref(
            var.get("arg").context("a map() reference has no \"arg\"")?,
        )?))),
        "zip" => Ok(Arg::Zip {
            args: parse_args(var)?,
            fillvalue: var.get("fillvalue").cloned(),
        }),
        "concat" => Ok(Arg::Concat(parse_args(var)?)),
        other => bail!("unknown XCom reference type {other:?}"),
    }
}

fn parse_arg(value: &Json, xcoms: &XComValues) -> Result<Arg> {
    match as_encoded(value) {
        Some(("xcomref", var)) => parse_ref(var),
        _ => Ok(Arg::Items(find_items(
            decode(value, xcoms)?,
            "a literal expand argument",
        )?)),
    }
}

impl Arg {
    fn find_len(&self, xcoms: &XComValues) -> Result<usize> {
        Ok(match self {
            Arg::Items(items) => items.len(),
            Arg::XCom { task_id, key } => find_items(
                read_xcom(xcoms, task_id, key)?.clone(),
                &format!("the XCom {task_id}/{key}"),
            )?
            .len(),
            Arg::Map(arg) => arg.find_len(xcoms)?,
            Arg::Zip { args, fillvalue } => {
                let lengths = args
                    .iter()
                    .map(|a| a.find_len(xcoms))
                    .collect::<Result<Vec<_>>>()?;
                let pick = if fillvalue.is_some() {
                    Iterator::max
                } else {
                    Iterator::min
                };
                pick(lengths.into_iter()).unwrap_or(0)
            }
            Arg::Concat(args) => args
                .iter()
                .map(|a| a.find_len(xcoms))
                .sum::<Result<usize>>()?,
        })
    }

    /// Element `index`, which must be below `find_len`.
    fn pick(&self, index: usize, xcoms: &XComValues) -> Result<Json> {
        match self {
            Arg::Items(items) => Ok(items[index].clone()),
            Arg::XCom { task_id, key } => Ok(find_items(
                read_xcom(xcoms, task_id, key)?.clone(),
                &format!("the XCom {task_id}/{key}"),
            )?
            .swap_remove(index)),
            Arg::Map(arg) => arg.pick(index, xcoms),
            Arg::Zip { args, fillvalue } => args
                .iter()
                .map(|a| {
                    if index < a.find_len(xcoms)? {
                        a.pick(index, xcoms)
                    } else {
                        Ok(fillvalue.clone().unwrap_or(Json::Null))
                    }
                })
                .collect::<Result<_>>()
                .map(Json::Array),
            Arg::Concat(args) => {
                let mut index = index;
                for arg in args {
                    let len = arg.find_len(xcoms)?;
                    if index < len {
                        return arg.pick(index, xcoms);
                    }
                    index -= len;
                }
                bail!("concat() index out of range")
            }
        }
    }

    fn is_map(&self) -> bool {
        matches!(self, Arg::Map(_))
    }
}

/// A mapped task's expansion, resolved against the XComs from `--input`.
#[derive(Debug)]
pub struct Expansion<'a> {
    input: ExpandInput,
    /// The `partial()` arguments, still serialized.
    partial: Map<String, Json>,
    xcoms: &'a XComValues,
    mapped_tasks: &'a BTreeSet<String>,
    pub length: usize,
}

impl<'a> Expansion<'a> {
    pub fn new(
        spec: &MappedSpec,
        xcoms: &'a XComValues,
        mapped_tasks: &'a BTreeSet<String>,
    ) -> Result<Self> {
        let value = spec
            .expand_input
            .get("value")
            .context("the expand input has no \"value\"")?;
        let input = match spec.expand_input.get("type").and_then(Json::as_str) {
            Some("dict-of-lists") => {
                let map = as_encoded(value)
                    .map_or(value, |(_, var)| var)
                    .as_object()
                    .context("an expand() input is not a dict")?;
                let args = map
                    .iter()
                    .map(|(name, v)| {
                        parse_arg(v, xcoms)
                            .with_context(|| format!("expand argument {name:?}"))
                            .map(|a| (name.clone(), a))
                    })
                    .collect::<Result<Vec<_>>>()?;
                let lengths = args
                    .iter()
                    .map(|(name, a)| {
                        a.find_len(xcoms)
                            .with_context(|| format!("expand argument {name:?}"))
                    })
                    .collect::<Result<_>>()?;
                ExpandInput::DictOfLists { args, lengths }
            }
            Some("list-of-dicts") => {
                ExpandInput::ListOfDicts(parse_arg(value, xcoms).context("expand_kwargs() input")?)
            }
            other => bail!("unknown expand input type {other:?}"),
        };
        let length = match &input {
            ExpandInput::DictOfLists { lengths, .. } => lengths.iter().product(),
            ExpandInput::ListOfDicts(arg) => arg.find_len(xcoms)?,
        };
        let partial = if spec.op_kwargs {
            spec.partial_kwargs.get("op_kwargs")
        } else {
            Some(&spec.partial_kwargs)
        };
        let partial = partial
            .map(|p| as_encoded(p).map_or(p, |(_, var)| var))
            .and_then(Json::as_object)
            .cloned()
            .unwrap_or_default();
        Ok(Self {
            input,
            partial,
            xcoms,
            mapped_tasks,
            length,
        })
    }

    /// The bindings the runtime receives for instance `map_index`, from the task's own
    /// `_arg_bindings`.
    pub fn build_bindings(&self, entries: &[Json], map_index: usize) -> Result<Vec<Json>> {
        entries
            .iter()
            .map(|entry| match entry.get("kind").and_then(Json::as_str) {
                Some("param") => self.resolve_param(entry, map_index),
                Some("kwargs") => self.resolve_kwargs(map_index),
                _ => Ok(entry.clone()),
            })
            .collect()
    }

    fn resolve_kwargs(&self, map_index: usize) -> Result<Json> {
        let ExpandInput::ListOfDicts(arg) = &self.input else {
            bail!("a \"kwargs\" binding needs an expand_kwargs() input");
        };
        let value = arg.pick(map_index, self.xcoms)?;
        if arg.is_map() {
            return Ok(
                json!({"kind": "literal", "value": value, "spread": true, "apply_map": true}),
            );
        }
        if !value.is_object() {
            bail!("element {map_index} of the expand_kwargs() input is {value}, not an object");
        }
        Ok(json!({"kind": "literal", "value": value, "spread": true}))
    }

    fn resolve_param(&self, entry: &Json, map_index: usize) -> Result<Json> {
        let name = entry
            .get("name")
            .and_then(Json::as_str)
            .context("a \"param\" binding has no \"name\"")?;
        if entry.get("group_arg").is_some_and(|g| !g.is_null()) {
            bail!(
                "parameter {name:?} reads an argument of a mapped task group, which gust does not expand yet"
            );
        }
        let mut binding = json!({"kind": "literal", "name": name});
        if let Some(schema) = entry.get("value_schema") {
            binding["value_schema"] = schema.clone();
        }
        match &self.input {
            ExpandInput::DictOfLists { args, lengths } => {
                if let Some(pos) = args.iter().position(|(n, _)| n == name) {
                    let arg = &args[pos].1;
                    binding["value"] =
                        arg.pick(find_dict_index(lengths, pos, map_index), self.xcoms)?;
                    if arg.is_map() {
                        binding["apply_map"] = json!(true);
                    }
                    return Ok(binding);
                }
            }
            ExpandInput::ListOfDicts(arg) => {
                let element = arg.pick(map_index, self.xcoms)?;
                if arg.is_map() {
                    binding["value"] = element;
                    binding["apply_map"] = json!(true);
                    binding["kwarg"] = json!(name);
                    if let Some(mut fallback) = self.find_fallback(entry, name)? {
                        if let Some(map) = fallback.as_object_mut() {
                            map.remove("from_default");
                        }
                        binding["fallback"] = fallback;
                    }
                    return Ok(binding);
                }
                let Json::Object(mut element) = element else {
                    bail!("element {map_index} of the expand_kwargs() input is not an object");
                };
                if let Some(value) = element.remove(name) {
                    binding["value"] = value;
                    return Ok(binding);
                }
            }
        }
        match self.find_fallback(entry, name)? {
            Some(mut fallback) => {
                fallback["name"] = json!(name);
                if let Some(schema) = entry.get("value_schema") {
                    fallback["value_schema"] = schema.clone();
                }
                Ok(fallback)
            }
            None => bail!(
                "parameter {name:?} of map index {map_index} gets no value from the expand input, partial() or a default"
            ),
        }
    }

    /// The binding for a parameter's `partial()` value, else its default.
    fn find_fallback(&self, entry: &Json, name: &str) -> Result<Option<Json>> {
        if let Some(value) = self.partial.get(name) {
            if let Some(("xcomref", var)) = as_encoded(value)
                && let Arg::XCom { task_id, .. } = parse_ref(var)?
                && self.mapped_tasks.contains(&task_id)
            {
                return Ok(Some(json!({"kind": "sequence", "task_id": task_id})));
            }
            let value = decode(value, self.xcoms)
                .with_context(|| format!("partial() argument {name:?}"))?;
            return Ok(Some(json!({"kind": "literal", "value": value})));
        }
        Ok(entry
            .get("default")
            .map(|d| json!({"kind": "literal", "value": d, "from_default": true})))
    }
}

/// Which item of argument `pos` instance `map_index` takes, as Python's
/// `DictOfListsExpandInput` works it out: the last argument varies fastest.
fn find_dict_index(lengths: &[usize], pos: usize, map_index: usize) -> usize {
    let mut index = map_index;
    for (p, len) in lengths.iter().enumerate().rev() {
        if p == pos {
            return index % len;
        }
        index /= len;
    }
    unreachable!("argument position out of range")
}

#[cfg(test)]
mod tests {
    use super::*;

    fn xcoms(entries: &[(&str, Json)]) -> XComValues {
        entries
            .iter()
            .map(|(task, v)| ((task.to_string(), "return_value".into()), v.clone()))
            .collect()
    }

    fn spec(expand_input: Json, partial: Json) -> MappedSpec {
        MappedSpec {
            expand_input,
            partial_kwargs: json!({"op_kwargs": {"__type": "dict", "__var": partial}}),
            op_kwargs: true,
        }
    }

    fn dict_of_lists(args: Json) -> Json {
        json!({"type": "dict-of-lists", "value": {"__type": "dict", "__var": args}})
    }

    fn xref(var: Json) -> Json {
        json!({"__type": "xcomref", "__var": var})
    }

    fn param(name: &str) -> Json {
        json!({"kind": "param", "name": name})
    }

    fn values(bindings: &[Json]) -> Vec<Json> {
        bindings.iter().map(|b| b["value"].clone()).collect()
    }

    #[test]
    fn crosses_expand_arguments_last_fastest() {
        let none = XComValues::new();
        let mapped = BTreeSet::new();
        let spec = spec(
            dict_of_lists(json!({"a": [1, 2], "b": ["x", "y", "z"]})),
            json!({}),
        );
        let exp = Expansion::new(&spec, &none, &mapped).unwrap();
        assert_eq!(exp.length, 6);
        let b = exp.build_bindings(&[param("a"), param("b")], 4).unwrap();
        assert_eq!(values(&b), [json!(2), json!("y")]);
        assert_eq!(b[0], json!({"kind": "literal", "name": "a", "value": 2}));
    }

    #[test]
    fn expands_over_upstream_lists_and_dicts() {
        let x = xcoms(&[
            ("rows", json!(["uk", "fr"])),
            ("lookup", json!({"k": 1, "j": 2})),
        ]);
        let mapped = BTreeSet::new();
        let spec = spec(
            dict_of_lists(json!({
                "row": xref(json!({"task_id": "rows", "key": "return_value"})),
                "pair": xref(json!({"task_id": "lookup"})),
            })),
            json!({}),
        );
        let exp = Expansion::new(&spec, &x, &mapped).unwrap();
        assert_eq!(exp.length, 4);
        let b = exp
            .build_bindings(&[param("row"), param("pair")], 1)
            .unwrap();
        assert_eq!(values(&b), [json!("uk"), json!(["j", 2])]);
    }

    #[test]
    fn rejects_missing_and_unmappable_xcoms() {
        let mapped = BTreeSet::new();
        let spec = spec(
            dict_of_lists(json!({"row": xref(json!({"task_id": "rows"}))})),
            json!({}),
        );
        let err = Expansion::new(&spec, &XComValues::new(), &mapped).unwrap_err();
        assert!(format!("{err:#}").contains("rows/return_value"), "{err:#}");
        let x = xcoms(&[("rows", json!("text"))]);
        let err = Expansion::new(&spec, &x, &mapped).unwrap_err();
        assert!(
            format!("{err:#}").contains("cannot be expanded over"),
            "{err:#}"
        );
    }

    #[test]
    fn zips_concats_and_maps() {
        let x = xcoms(&[("a", json!([1, 2, 3])), ("b", json!(["x"]))]);
        let mapped = BTreeSet::new();
        let zip = |fill: Option<Json>| {
            let mut var = json!({"type": "zip", "args": [{"task_id": "a"}, {"task_id": "b"}]});
            if let Some(fill) = fill {
                var["fillvalue"] = fill;
            }
            spec(dict_of_lists(json!({"v": xref(var)})), json!({}))
        };
        let short = zip(None);
        assert_eq!(Expansion::new(&short, &x, &mapped).unwrap().length, 1);
        let long = zip(Some(json!("-")));
        let exp = Expansion::new(&long, &x, &mapped).unwrap();
        assert_eq!(exp.length, 3);
        assert_eq!(
            exp.build_bindings(&[param("v")], 2).unwrap()[0]["value"],
            json!([3, "-"])
        );

        let concat = spec(
            dict_of_lists(
                json!({"v": xref(json!({"type": "concat", "args": [{"task_id": "a"}, {"task_id": "b"}]}))}),
            ),
            json!({}),
        );
        let exp = Expansion::new(&concat, &x, &mapped).unwrap();
        assert_eq!(exp.length, 4);
        assert_eq!(
            exp.build_bindings(&[param("v")], 3).unwrap()[0]["value"],
            "x"
        );

        let map = spec(
            dict_of_lists(
                json!({"v": xref(json!({"type": "map", "arg": {"task_id": "a"}, "callables": ["f"]}))}),
            ),
            json!({}),
        );
        let exp = Expansion::new(&map, &x, &mapped).unwrap();
        let b = &exp.build_bindings(&[param("v")], 1).unwrap()[0];
        assert_eq!((&b["value"], &b["apply_map"]), (&json!(2), &json!(true)));

        let nested = spec(
            dict_of_lists(
                json!({"v": xref(json!({"type": "zip", "args": [{"type": "map", "arg": {"task_id": "a"}, "callables": []}, {"task_id": "b"}]}))}),
            ),
            json!({}),
        );
        let err = Expansion::new(&nested, &x, &mapped).unwrap_err();
        assert!(format!("{err:#}").contains("outermost"), "{err:#}");
    }

    #[test]
    fn falls_back_to_partial_then_default() {
        let x = xcoms(&[("totals", json!([1, 2])), ("conf", json!({"k": "v"}))]);
        let mapped = BTreeSet::from(["totals".to_owned()]);
        let spec = spec(
            json!({"type": "list-of-dicts", "value": [
                {"__type": "dict", "__var": {"row": "a", "scale": 3}},
                {"__type": "dict", "__var": {"row": "b"}},
            ]}),
            json!({
                "region": "eu",
                "conf": xref(json!({"task_id": "conf"})),
                "totals": xref(json!({"task_id": "totals"})),
            }),
        );
        let exp = Expansion::new(&spec, &x, &mapped).unwrap();
        assert_eq!(exp.length, 2);
        let entries = [
            param("row"),
            json!({"kind": "param", "name": "scale", "default": 2}),
            param("region"),
            param("conf"),
            param("totals"),
            json!({"kind": "xcom", "name": "other", "task_id": "up"}),
        ];
        let b = exp.build_bindings(&entries, 1).unwrap();
        assert_eq!(b[0]["value"], "b");
        assert_eq!(
            b[1],
            json!({"kind": "literal", "name": "scale", "value": 2, "from_default": true})
        );
        assert_eq!(b[2]["value"], "eu");
        assert_eq!(b[3]["value"], json!({"k": "v"}));
        assert_eq!(
            b[4],
            json!({"kind": "sequence", "name": "totals", "task_id": "totals"})
        );
        assert_eq!(b[5], entries[5]);
        assert_eq!(exp.build_bindings(&entries, 0).unwrap()[1]["value"], 3);

        let err = exp.build_bindings(&[param("missing")], 0).unwrap_err();
        assert!(format!("{err:#}").contains("map index 0"), "{err:#}");
    }

    #[test]
    fn leaves_kwarg_to_a_mapping_runtime() {
        let x = xcoms(&[("rows", json!([{"row": "a"}]))]);
        let mapped = BTreeSet::new();
        let spec = spec(
            json!({"type": "list-of-dicts", "value": xref(json!({"type": "map", "arg": {"task_id": "rows"}, "callables": []}))}),
            json!({"row": "z"}),
        );
        let exp = Expansion::new(&spec, &x, &mapped).unwrap();
        let b = exp.build_bindings(&[param("row")], 0).unwrap();
        assert_eq!(
            b[0],
            json!({"kind": "literal", "name": "row", "value": {"row": "a"}, "apply_map": true,
                   "kwarg": "row", "fallback": {"kind": "literal", "value": "z"}})
        );
    }

    #[test]
    fn spreads_a_kwargs_entry() {
        let x = xcoms(&[("rows", json!([{"a": 1}, {"a": 2}]))]);
        let mapped = BTreeSet::new();
        let spec = spec(
            json!({"type": "list-of-dicts", "value": xref(json!({"task_id": "rows"}))}),
            json!({}),
        );
        let exp = Expansion::new(&spec, &x, &mapped).unwrap();
        let b = exp.build_bindings(&[json!({"kind": "kwargs"})], 1).unwrap();
        assert_eq!(
            b[0],
            json!({"kind": "literal", "value": {"a": 2}, "spread": true})
        );
    }

    #[test]
    fn refuses_mapped_task_group_arguments() {
        let none = XComValues::new();
        let mapped = BTreeSet::new();
        let spec = spec(dict_of_lists(json!({"a": [1]})), json!({}));
        let exp = Expansion::new(&spec, &none, &mapped).unwrap();
        let entry =
            json!({"kind": "param", "name": "x", "group_arg": {"group_id": "g", "key": "x"}});
        assert!(exp.build_bindings(&[entry], 0).is_err());
    }
}
