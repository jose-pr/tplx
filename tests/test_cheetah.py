"""The Cheetah engine: a Cobbler-style kickstart, includes and undefined names."""

from types import SimpleNamespace

import pytest

pytest.importorskip("Cheetah", reason="needs the 'cheetah' extra")

from tplx import (  # noqa: E402
    CheetahTemplate,
    Loader,
    TemplateNotFound,
    UndefinedError,
)

KICKSTART = """\
#set global $fqdn = $target.hostname + '.' + $domain
network --hostname=$fqdn
#for $ns in $nameservers
nameserver $ns
#end for
#if $target.raid
part raid
#else
part /
#end if
#include "snippets/post"
"""


def test_a_kickstart_renders(tree):
    tree.write("ks.cfg.cheetah", KICKSTART)
    tree.write("snippets/post.cheetah", "%post\necho $fqdn\n%end\n")
    data = {
        "target": SimpleNamespace(hostname="web01", raid=False),
        "domain": "lan",
        "nameservers": ["10.0.0.53", "10.0.0.54"],
    }
    assert Loader([tree.root]).render("ks.cfg", data) == (
        "network --hostname=web01.lan\n"
        "nameserver 10.0.0.53\n"
        "nameserver 10.0.0.54\n"
        "part /\n"
        "%post\necho web01.lan\n%end\n"
    )


def test_includes_go_through_the_lookup_nested_and_raw(tree):
    tree.write("page.cheetah", '#include "part"\n#include raw "part"\n')
    tree.write("part.cheetah", '[$n]#include "inner"\n')
    tree.write("inner.cheetah", "<$n>")
    assert Loader([tree.root]).render("page", n=1) == ('[1]<1>\n[$n]#include "inner"\n')


def test_another_engines_file_is_rendered_and_inserted(tree):
    tree.write("net.shtpl", "IP=%{IP}\n")
    tree.write("page.cheetah", '#include "net"\ndone\n')
    assert Loader([tree.root]).render("page", ip="1.2.3.4") == "IP=1.2.3.4\ndone\n"


def test_an_undefined_name_follows_the_mode(tree):
    tree.write("page.cheetah", "#include 'net'\n[$nope] [$n]\n")
    tree.write("net.shtpl", "x\n")
    with pytest.raises(UndefinedError, match="nope"):
        Loader([tree.root]).render("page", n=1)
    assert Loader([tree.root], undefined="lenient").render("page", n=1) == "x\n[] [1]\n"
    assert (
        Loader([tree.root], undefined="debug").render("page", n=1) == "x\n[$nope] [1]\n"
    )


def test_a_missing_include_raises_only_when_strict(tree):
    tree.write("page.cheetah", 'a\n#include "gone"\nb\n')
    with pytest.raises(TemplateNotFound):
        Loader([tree.root]).render("page")
    assert Loader([tree.root], undefined="lenient").render("page") == "a\nb\n"


def test_configure_receives_the_compiler_settings(tree):
    tree.write("page.cheetah", "@n is @{n}")
    loader = Loader(
        [tree.root],
        configure={
            CheetahTemplate: lambda settings: settings.update(cheetahVarStartToken="@")
        },
    )
    assert loader.render("page", n=3) == "3 is 3"
