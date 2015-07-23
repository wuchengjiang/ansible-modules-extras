#!/usr/bin/python
# This file is part of Ansible
#
# Ansible is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
#
# Ansible is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with Ansible.  If not, see <http://www.gnu.org/licenses/>.

DOCUMENTATION = '''
---
module: profitbricks
short_description: Create, destroy, start, stop, and reboot a ProfitBricks virtual machine.
description:
     - Create, destroy, update, start, stop, and reboot a ProfitBricks virtual machine. When the virtual machine is created it can optionally wait for it to be 'running' before returning. This module has a dependency on profitbricks >= 1.0.0
version_added: "2.0"
options:
  auto_increment:
    description:
      - Whether or not to increment a single number in the name for created virtual machines.
    default: yes
    choices: ["yes", "no"]
  name:
    description:
      - The name of the virtual machine.
    required: true
  image: 
    description:
      - The system image ID for creating the virtual machine, e.g. a3eae284-a2fe-11e4-b187-5f1f641608c8.
    required: true
  datacenter:
    description:
      - The Datacenter to provision this virtual machine.
    required: false
    default: null
  cores:
    description:
      - The number of CPU cores to allocate to the virtual machine.
    required: false
    default: 2
  ram:
    description:
      - The amount of memory to allocate to the virtual machine.
    required: false
    default: 2048
  volume_size:
    description:
      - The size in GB of the boot volume.
    required: false
    default: 10
  bus:
    description:
      - The bus type for the volume.
    required: false
    default: VIRTIO
    choices: [ "IDE", "VIRTIO"]
  instance_ids:
    description:
      - list of instance ids, currently only used when state='absent' to remove instances.
    required: false
  count:
    description:
      - The number of virtual machines to create.
    required: false
    default: 1
  location:
    description:
      - The datacenter location. Use only if you want to create the Datacenter or else this value is ignored. 
    required: false
    default: us/las
    choices: [ "us/las", "us/lasdev", "de/fra", "de/fkb" ]
  assign_public_ip:
    description:
      - This will assign the machine to the public LAN. If no LAN exists with public Internet access it is created.
    required: false
    default: false
  lan:
    description:
      - The ID of the LAN you wish to add the servers to.
    required: false
    default: 1
  subscription_user:
    description:
      - The ProfitBricks username. Overrides the PB_SUBSCRIPTION_ID environement variable.
    required: false
    default: null
  subscription_password:
    description:
      - THe ProfitBricks password. Overrides the PB_PASSWORD environement variable.
    required: false
    default: null
  wait:
    description:
      - wait for the instance to be in state 'running' before returning
    required: false
    default: "yes"
    choices: [ "yes", "no" ]
  wait_timeout:
    description:
      - how long before wait gives up, in seconds
    default: 600
  remove_boot_volume:
    description:
      - remove the bootVolume of the virtual machine you're destroying.
    required: false
    default: "yes"
    choices: ["yes", "no"]
  state:
    description:
      - create or terminate instances
    required: false
    default: 'present'
    choices: [ "running", "stopped", "absent", "present" ]

requirements:
     - "profitbricks"
     - "python >= 2.6"
author: Matt Baldwin (baldwin@stackpointcloud.com)
'''

EXAMPLES = '''

# Note: These examples do not set authentication details, see the AWS Guide for details.

# Provisioning example. This will create three servers and enumerate their names. 

- profitbricks:
    datacenter: Tardis One
    name: web%02d.stackpointcloud.com
    cores: 4
    ram: 2048
    volume_size: 50
    image: a3eae284-a2fe-11e4-b187-5f1f641608c8
    location: us/las
    count: 3
    assign_public_ip: true

# Removing Virtual machines

- profitbricks:
    datacenter: Tardis One
    instance_ids:
      - 'web001.stackpointcloud.com'
      - 'web002.stackpointcloud.com'
      - 'web003.stackpointcloud.com'
    wait_timeout: 500
    state: absent

# Starting Virtual Machines.

- profitbricks:
    datacenter: Tardis One
    instance_ids:
      - 'web001.stackpointcloud.com'
      - 'web002.stackpointcloud.com'
      - 'web003.stackpointcloud.com'
    wait_timeout: 500
    state: running

# Stopping Virtual Machines

- profitbricks:
    datacenter: Tardis One
    instance_ids:
      - 'web001.stackpointcloud.com'
      - 'web002.stackpointcloud.com'
      - 'web003.stackpointcloud.com'
    wait_timeout: 500
    state: stopped

'''

import re
import uuid
import time

HAS_PB_SDK = True

try:
    from profitbricks.client import ProfitBricksService, Volume, Server, Datacenter, NIC, LAN
except ImportError:
    HAS_PB_SDK = False

LOCATIONS = ['us/las',
             'de/fra',
             'de/fkb',
             'us/lasdev']

uuid_match = re.compile(
    '[\w]{8}-[\w]{4}-[\w]{4}-[\w]{4}-[\w]{12}', re.I)


def _wait_for_completion(profitbricks, promise, wait_timeout, msg):
    if not promise: return
    wait_timeout = time.time() + wait_timeout
    while wait_timeout > time.time():
        time.sleep(5)
        operation_result = profitbricks.get_request(
            request_id=promise['requestId'],
            status=True)

        if operation_result['metadata']['status'] == "DONE":
            return
        elif operation_result['metadata']['status'] == "FAILED":
            raise Exception(
                'Request failed to complete ' + msg + ' "' + str(
                    promise['requestId']) + '" to complete.')

    raise Exception(
        'Timed out waiting for async operation ' + msg + ' "' + str(
            promise['requestId']
            ) + '" to complete.')

def _create_machine(module, profitbricks, datacenter, name):
    image = module.params.get('image')
    cores = module.params.get('cores')
    ram = module.params.get('ram')
    volume_size = module.params.get('volume_size')
    bus = module.params.get('bus')
    lan = module.params.get('lan')
    assign_public_ip = module.params.get('assign_public_ip')
    subscription_user = module.params.get('subscription_user')
    subscription_password = module.params.get('subscription_password')
    location = module.params.get('location')
    image = module.params.get('image')
    assign_public_ip = module.boolean(module.params.get('assign_public_ip'))
    wait = module.params.get('wait')
    wait_timeout = module.params.get('wait_timeout')

    try:
        # Generate name, but grab first 10 chars so we don't
        # screw up the uuid match routine.
        v = Volume(
            name=str(uuid.uuid4()).replace('-','')[:10],
            size=volume_size,
            image=image,
            bus=bus)

        volume_response = profitbricks.create_volume(
            datacenter_id=datacenter, volume=v)

        # We're forced to wait on the volume creation since
        # server create relies upon this existing.

        _wait_for_completion(profitbricks, volume_response,
                             wait_timeout, "create_volume")
    except Exception as e:
        module.fail_json(msg="failed to create the new volume: %s" % str(e))

    if assign_public_ip:
        public_found = False

        lans = profitbricks.list_lans(datacenter)
        for lan in lans['items']:
            if lan['properties']['public']:
                public_found = True
                lan = lan['id']

        if not public_found:
            i = LAN(
                name='public',
                public=True)

            lan_response = profitbricks.create_lan(datacenter, i)

            lan = lan_response['id']

            _wait_for_completion(profitbricks, lan_response,
                                 wait_timeout, "_create_machine")

    try:
        n = NIC(
            lan=int(lan)
            )

        nics = [n]

        s = Server(
            name=name,
            ram=ram,
            cores=cores,
            nics=nics,
            boot_volume_id=volume_response['id']
            )

        server_response = profitbricks.create_server(
            datacenter_id=datacenter, server=s)

        if wait:
            _wait_for_completion(profitbricks, server_response,
                                 wait_timeout, "create_virtual_machine")


        return (server_response)
    except Exception as e:
        module.fail_json(msg="failed to create the new server: %s" % str(e))

def _remove_machine(module, profitbricks, datacenter, name):
    remove_boot_volume = module.params.get('remove_boot_volume')
    wait = module.params.get('wait')
    wait_timeout = module.params.get('wait_timeout')
    changed = False

    # User provided the actual UUID instead of the name.
    try:
        if remove_boot_volume:
            # Collect information needed for later. 
            server = profitbricks.get_server(datacenter, name)
            volume_id = server['properties']['bootVolume']['href'].split('/')[7]

        server_response = profitbricks.delete_server(datacenter, name)
        changed = True

    except Exception as e:
        module.fail_json(msg="failed to terminate the virtual server: %s" % str(e))

    # Remove the bootVolume
    if remove_boot_volume:
        try:
            volume_response = profitbricks.delete_volume(datacenter, volume_id)

        except Exception as e:
            module.fail_json(msg="failed to remove the virtual server's bootvolume: %s" % str(e))

    return changed

def _startstop_machine(module, profitbricks, datacenter, name):
    state = module.params.get('state')

    try:
        if state == 'running':
            profitbricks.start_server(datacenter, name)
        else:
            profitbricks.stop_server(datacenter, name)

        return True
    except Exception as e:
        module.fail_json(msg="failed to start or stop the virtual machine %s: %s" % (name, str(e)))

def _create_datacenter(module, profitbricks):
    datacenter = module.params.get('datacenter')
    location = module.params.get('location')
    wait_timeout = module.params.get('wait_timeout')

    i = Datacenter(
        name=datacenter,
        location=location
        )

    try:
        datacenter_response = profitbricks.create_datacenter(datacenter=i)

        _wait_for_completion(profitbricks, datacenter_response,
                             wait_timeout, "_create_datacenter")

        return datacenter_response
    except Exception as e:
        module.fail_json(msg="failed to create the new server(s): %s" % str(e))

def create_virtual_machine(module, profitbricks):
    """
    Create new virtual machine

    module : AnsibleModule object
    profitbricks: authenticated profitbricks object

    Returns:
        True if a new virtual machine was created, false otherwise
    """
    datacenter = module.params.get('datacenter')
    name = module.params.get('name')
    auto_increment = module.params.get('auto_increment')
    count = module.params.get('count')
    lan = module.params.get('lan')
    wait_timeout = module.params.get('wait_timeout')
    failed = True
    datacenter_found = False

    virtual_machines = []
    virtual_machine_ids = []

    # Locate UUID for Datacenter
    if not (uuid_match.match(datacenter)):
        datacenter_list = profitbricks.list_datacenters()
        for d in datacenter_list['items']:
            dc = profitbricks.get_datacenter(d['id'])
            if datacenter == dc['properties']['name']:
                datacenter = d['id']
                datacenter_found = True
                break

    if not datacenter_found:
        datacenter_response = _create_datacenter(module, profitbricks)
        datacenter = datacenter_response['id']

        _wait_for_completion(profitbricks, datacenter_response,
                             wait_timeout, "create_virtual_machine")

    if auto_increment:
        numbers = set()
        count_offset = 1

        try:
            name % 0
        except TypeError, e:
            if e.message.startswith('not all'):
                name = '%s%%d' % name
            else:
                module.fail_json(msg=e.message)

        number_range = xrange(count_offset,count_offset + count + len(numbers))
        available_numbers = list(set(number_range).difference(numbers))
        names = []
        numbers_to_use = available_numbers[:count]
        for number in numbers_to_use:
            names.append(name % number)
    else:
        names = [name] * count

    for name in  names: 
        create_response = _create_machine(module, profitbricks, str(datacenter), name)
        nics = profitbricks.list_nics(datacenter,create_response['id'])
        for n in nics['items']:
            if lan == n['properties']['lan']:
                create_response.update({ 'public_ip': n['properties']['ips'][0] })

        virtual_machines.append(create_response)
        failed = False

    results = {
        'failed': failed,
        'machines': virtual_machines,
        'action': 'create',
        'instance_ids': {
            'instances': [i['id'] for i in virtual_machines],
        }
    }

    return results

def remove_virtual_machine(module, profitbricks):
    """
    Removes a virtual machine. 

    This will remove the virtual machine along with the bootVolume.

    module : AnsibleModule object
    profitbricks: authenticated profitbricks object.

    Not yet supported: handle deletion of attached data disks.

    Returns:
        True if a new virtual server was deleted, false otherwise
    """
    if not isinstance(module.params.get('instance_ids'), list) or len(module.params.get('instance_ids')) < 1:
        module.fail_json(msg='instance_ids should be a list of virtual machine ids or names, aborting')

    datacenter = module.params.get('datacenter')
    instance_ids = module.params.get('instance_ids')

    # Locate UUID for Datacenter
    if not (uuid_match.match(datacenter)):
        datacenter_list = profitbricks.list_datacenters()
        for d in datacenter_list['items']:
            dc = profitbricks.get_datacenter(d['id'])
            if datacenter == dc['properties']['name']:
                datacenter = d['id']
                break

    for n in instance_ids:
        if(uuid_match.match(n)):
            _remove_machine(module, profitbricks, d['id'], n)
        else:
            servers = profitbricks.list_servers(d['id'])

            for s in servers['items']:
                if n == s['properties']['name']:
                    server_id = s['id']

                    _remove_machine(module, profitbricks, datacenter, server_id)

def startstop_machine(module, profitbricks, state):
    """
    Starts or Stops a virtual machine. 

    module : AnsibleModule object
    profitbricks: authenticated profitbricks object.

    Returns:
        True when the servers process the action successfully, false otherwise.
    """
    if not isinstance(module.params.get('instance_ids'), list) or len(module.params.get('instance_ids')) < 1:
        module.fail_json(msg='instance_ids should be a list of virtual machine ids or names, aborting')

    wait = module.params.get('wait')
    wait_timeout = module.params.get('wait_timeout')
    changed = False

    datacenter = module.params.get('datacenter')
    instance_ids = module.params.get('instance_ids')

    # Locate UUID for Datacenter
    if not (uuid_match.match(datacenter)):
        datacenter_list = profitbricks.list_datacenters()
        for d in datacenter_list['items']:
            dc = profitbricks.get_datacenter(d['id'])
            if datacenter == dc['properties']['name']:
                datacenter = d['id']
                break

    for n in instance_ids:
        if(uuid_match.match(n)):
            _startstop_machine(module, profitbricks, datacenter, n)

            changed = True
        else:
            servers = profitbricks.list_servers(d['id'])

            for s in servers['items']:
                if n == s['properties']['name']:
                    server_id = s['id']
                    _startstop_machine(module, profitbricks, datacenter, server_id)

                    changed = True

    if wait:
        wait_timeout = time.time() + wait_timeout
        while wait_timeout > time.time():
            matched_instances = []
            for res in profitbricks.list_servers(datacenter)['items']:
                if state == 'running':
                    if res['properties']['vmState'].lower() == state:
                        matched_instances.append(res)
                elif state == 'stopped':
                    if res['properties']['vmState'].lower() == 'shutoff':
                        matched_instances.append(res)                    

            if len(matched_instances) < len(instance_ids):
                time.sleep(5)
            else:
                break

        if wait_timeout <= time.time():
            # waiting took too long
            module.fail_json(msg = "wait for virtual machine state timeout on %s" % time.asctime())

    return (changed)

def main():
    module = AnsibleModule(
        argument_spec=dict(
            datacenter=dict(),
            name=dict(),
            image=dict(),
            cores=dict(default=2),
            ram=dict(default=2048),
            volume_size=dict(default=10),
            bus=dict(default='VIRTIO'),
            lan=dict(default=1),
            count=dict(default=1),
            auto_increment=dict(type='bool', default=True),
            instance_ids=dict(),
            subscription_user=dict(),
            subscription_password=dict(),
            location=dict(choices=LOCATIONS, default='us/las'),
            assign_public_ip=dict(type='bool', default=False),
            wait=dict(type='bool', default=True),
            wait_timeout=dict(type='int', default=600),
            remove_boot_volume=dict(type='bool', default=True),
            state=dict(default='present'),
        )
    )

    if not HAS_PB_SDK:
        module.fail_json(msg='profitbricks required for this module')

    subscription_user = module.params.get('subscription_user')
    subscription_password = module.params.get('subscription_password')
    wait = module.params.get('wait')
    wait_timeout = module.params.get('wait_timeout')

    profitbricks = ProfitBricksService(
        username=subscription_user,
        password=subscription_password)

    state = module.params.get('state')

    if state == 'absent':
        if not module.params.get('datacenter'):
            module.fail_json(msg='datacenter parameter is required ' + 
                'for running or stopping machines.')

        try:
            (changed) = remove_virtual_machine(module, profitbricks)
            module.exit_json(changed=changed)
        except Exception as e:
            module.fail_json(msg='failed to set instance state: %s' % str(e))

    elif state in ('running', 'stopped'):
        if not module.params.get('datacenter'):
            module.fail_json(msg='datacenter parameter is required for ' + 
                'running or stopping machines.')
        try:
            (changed) = startstop_machine(module, profitbricks, state)
            module.exit_json(changed=changed)
        except Exception as e:
            module.fail_json(msg='failed to set instance state: %s' % str(e))

    elif state == 'present':
        if not module.params.get('name'):
            module.fail_json(msg='name parameter is required for new instance')
        if not module.params.get('image'):
            module.fail_json(msg='image parameter is required for new instance')
        if not module.params.get('subscription_user'):
            module.fail_json(msg='subscription_user parameter is ' + 
                'required for new instance')
        if not module.params.get('subscription_password'):
            module.fail_json(msg='subscription_password parameter is ' + 
                'required for new instance')

        try:
            (machine_dict_array) = create_virtual_machine(module, profitbricks)
            module.exit_json(**machine_dict_array)
        except Exception as e:
            module.fail_json(msg='failed to set instance state: %s' % str(e))

from ansible.module_utils.basic import *

main()
