=========
Saltclass
=========

Saltclass consists of external pillar and master top modules:

.. toctree::
    :maxdepth: 1

    ../../ref/tops/all/salt.tops.saltclass
    ../../ref/pillar/all/salt.pillar.saltclass

It clones the behaviour of reclass (http://reclass.pantsfullofunix.net/), without the need of an external app, and adds several features to improve flexibility.
Saltclass lets you define your nodes from simple ``yaml`` files (``.yml``) through hierarchical class inheritance with the possibility to override pillars down the tree.

**Features**

- Define your nodes through hierarchical class inheritance

- Reuse your reclass data with minimal modifications

    - applications => states

    - parameters => pillars

    - __reclass__ => __saltclass__

- Use Jinja templating in your yaml definitions

- Access to the following Salt objects in Jinja

    - ``opts``

    - ``salt``

    - ``grains``

    - ``pillar``

- Chose how to merge or override your lists using ^ character (see examples)

- Expand variables ${} with possibility to escape them if needed \${} (see
  examples)

- Ignores missing node/class and will simply return empty without breaking the
  pillar module completely - will be logged

An example subset of data is available here:
http://git.mauras.ch/salt/saltclass/src/master/examples

==========================  ===========
Terms usable in yaml files  Description
==========================  ===========
classes                     A list of classes that will be processed in order
states                      A list of states that will be returned by master_tops function
pillars                     A yaml dictionary that will be returned by the ext_pillar function
environment                 Node saltenv that will be used by master_tops
==========================  ===========

A class consists of:

- zero or more parent classes
- zero or more states
- any number of pillars

A child class can override pillars from a parent class. A node definition is a
class in itself with an added ``environment`` parameter for ``saltenv``
definition.

**Class Names**

Class names mimic salt way of defining states and pillar files.
This means that ``default.users`` class name will correspond to one of these:

- ``<saltclass_path>/classes/default/users.yml``
- ``<saltclass_path>/classes/default/users/init.yml``

**Saltclass Tree**

A saltclass tree would look like this:

.. code-block:: text

    <saltclass_path>
    ├── classes
    │   ├── app
    │   │   ├── borgbackup.yml
    │   │   └── ssh
    │   │       └── server.yml
    │   ├── default
    │   │   ├── init.yml
    │   │   ├── motd.yml
    │   │   └── users.yml
    │   ├── roles
    │   │   ├── app.yml
    │   │   └── nginx
    │   │       ├── init.yml
    │   │       └── server.yml
    │   └── subsidiaries
    │       ├── gnv.yml
    │       ├── qls.yml
    │       └── zrh.yml
    └── nodes
        ├── geneva
        │   └── gnv.node1.yml
        ├── lausanne
        │   ├── qls.node1.yml
        │   └── qls.node2.yml
        ├── node127.yml
        └── zurich
            ├── zrh.node1.yml
            ├── zrh.node2.yml
            └── zrh.node3.yml

**Examples**

``<saltclass_path>/nodes/lausanne/qls.node1.yml``

.. code-block:: jinja

    environment: base

    classes:
    {% for class in ['default'] %}
      - {{ class }}
    {% endfor %}
      - subsidiaries.{{ __grains__['id'].split('.')[0] }}

``<saltclass_path>/classes/default/init.yml``

.. code-block:: yaml

    classes:
      - default.users
      - default.motd

    states:
      - openssh

    pillars:
      default:
        network:
          dns:
            srv1: 192.168.0.1
            srv2: 192.168.0.2
            domain: example.com
        ntp:
          srv1: 192.168.10.10
          srv2: 192.168.10.20

``<saltclass_path>/classes/subsidiaries/gnv.yml``

.. code-block:: yaml

    pillars:
      default:
        network:
          sub: Geneva
          dns:
            srv1: 10.20.0.1
            srv2: 10.20.0.2
            srv3: 192.168.1.1
            domain: gnv.example.com
        users:
          adm1:
            uid: 1210
            gid: 1210
            gecos: 'Super user admin1'
            homedir: /srv/app/adm1
          adm3:
            uid: 1203
            gid: 1203
            gecos: 'Super user adm

Variable expansions:

Escaped variables are rendered as is - ``${test}``

Missing variables are rendered as is - ``${net:dns:srv2}``

.. code-block:: yaml

    pillars:
      app:
      config:
        dns:
          srv1: ${default:network:dns:srv1}
          srv2: ${net:dns:srv2}
        uri: https://application.domain/call?\${test}
        prod_parameters:
          - p1
          - p2
          - p3
      pkg:
        - app-core
        - app-backend

List override:

Not using ``^`` as the first entry will simply merge the lists

.. code-block:: yaml

    pillars:
      app:
        pkg:
          - ^
          - app-frontend


**Known limitation** (TODO: is it still relevant?)

Currently you can't have both a variable and an escaped variable in the same
string as the escaped one will not be correctly rendered - '\${xx}' will stay
as is instead of being rendered as '${xx}'
