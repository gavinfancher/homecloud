"""The small ISOs that make installs hands-off.

Proxmox's API can't upload cloud-init snippets, but it can upload ISOs. So homecloud builds
the install answers itself, packs them into a tiny ISO, and uploads that like any other ISO:

- Ubuntu: a NoCloud seed (label `cidata`) with user-data and meta-data. Every Ubuntu cloud
  image reads it on first boot.
- Windows: `autounattend.xml` at the root of a disc. Windows Setup searches every drive for it.

Both are deleted from Proxmox once the VM is up: the Windows one holds the admin password.
"""

import io
import uuid
from xml.sax.saxutils import escape

import pycdlib
import yaml

from app import config


def seed_iso_name(vmid: int) -> str:
    return f"homecloud-{vmid}-seed.iso"


def _iso(files: dict[str, str], label: str) -> bytes:
    """An ISO9660 disc holding *files*, with Joliet and Rock Ridge so the real names survive."""
    iso = pycdlib.PyCdlib()
    iso.new(interchange_level=3, joliet=3, rock_ridge="1.09", vol_ident=label)
    for name, content in files.items():
        data = content.encode()
        short = "/" + name.replace("-", "").replace(".", "").upper()[:8] + ".;1"
        iso.add_fp(io.BytesIO(data), len(data), short, rr_name=name, joliet_path=f"/{name}")
    out = io.BytesIO()
    iso.write_fp(out)
    iso.close()
    return out.getvalue()


# ---------- Ubuntu ----------

def ubuntu_user_data(hostname: str) -> str:
    doc = {
        "hostname": hostname,
        "users": [{
            "name": "ubuntu",
            "groups": ["sudo"],
            "shell": "/bin/bash",
            "sudo": "ALL=(ALL) NOPASSWD:ALL",
            "lock_passwd": True,
            "ssh_authorized_keys": config.SSH_KEYS,
        }],
        "ssh_pwauth": False,
        "package_update": True,
        # The guest agent is how homecloud (and Proxmox) see the VM's IP and know it's up.
        "packages": ["qemu-guest-agent"],
        "runcmd": [["systemctl", "enable", "--now", "qemu-guest-agent"]],
    }
    return "#cloud-config\n" + yaml.safe_dump(doc, sort_keys=False, width=4096)


def ubuntu_seed(hostname: str) -> bytes:
    meta = yaml.safe_dump({"instance-id": f"homecloud-{uuid.uuid4().hex}", "local-hostname": hostname})
    # No network-config: the cloud image's default is DHCP on the first NIC, which is what we want.
    return _iso({"user-data": ubuntu_user_data(hostname), "meta-data": meta}, "cidata")


# ---------- Windows ----------

# Finds the VirtIO disc, whatever letter it got, and installs its guest tools: the drivers for
# the virtio-serial port and the QEMU guest agent. When the agent answers, homecloud knows
# Windows has finished installing.
_INSTALL_GUEST_TOOLS = (
    "powershell -NoProfile -ExecutionPolicy Bypass -Command \""
    "$d = Get-PSDrive -PSProvider FileSystem | Where-Object { Test-Path ($_.Root + 'virtio-win-guest-tools.exe') } "
    "| Select-Object -First 1; "
    "if ($d) { Start-Process -Wait ($d.Root + 'virtio-win-guest-tools.exe') -ArgumentList '/install','/passive','/norestart' }\""
)

AUTOUNATTEND = """<?xml version="1.0" encoding="utf-8"?>
<!-- Windows 11, unattended. Built by homecloud from backend/app/media.py; same layout as the
     answer files in the AD-at-home repo. -->
<unattend xmlns="urn:schemas-microsoft-com:unattend" xmlns:wcm="http://schemas.microsoft.com/WMIConfig/2002/State">
  <settings pass="windowsPE">
    <component name="Microsoft-Windows-International-Core-WinPE" processorArchitecture="amd64" publicKeyToken="31bf3856ad364e35" language="neutral" versionScope="nonSxS">
      <SetupUILanguage><UILanguage>en-US</UILanguage></SetupUILanguage>
      <InputLocale>en-US</InputLocale>
      <SystemLocale>en-US</SystemLocale>
      <UILanguage>en-US</UILanguage>
      <UserLocale>en-US</UserLocale>
    </component>
    <component name="Microsoft-Windows-Setup" processorArchitecture="amd64" publicKeyToken="31bf3856ad364e35" language="neutral" versionScope="nonSxS">
      <!-- UEFI, so GPT: EFI system partition, MSR, then C:. -->
      <DiskConfiguration>
        <Disk wcm:action="add">
          <DiskID>0</DiskID>
          <WillWipeDisk>true</WillWipeDisk>
          <CreatePartitions>
            <CreatePartition wcm:action="add"><Order>1</Order><Type>EFI</Type><Size>300</Size></CreatePartition>
            <CreatePartition wcm:action="add"><Order>2</Order><Type>MSR</Type><Size>16</Size></CreatePartition>
            <CreatePartition wcm:action="add"><Order>3</Order><Type>Primary</Type><Extend>true</Extend></CreatePartition>
          </CreatePartitions>
          <ModifyPartitions>
            <ModifyPartition wcm:action="add"><Order>1</Order><PartitionID>1</PartitionID><Format>FAT32</Format><Label>System</Label></ModifyPartition>
            <ModifyPartition wcm:action="add"><Order>2</Order><PartitionID>2</PartitionID></ModifyPartition>
            <ModifyPartition wcm:action="add"><Order>3</Order><PartitionID>3</PartitionID><Format>NTFS</Format><Label>Windows</Label><Letter>C</Letter></ModifyPartition>
          </ModifyPartitions>
        </Disk>
      </DiskConfiguration>
      <ImageInstall>
        <OSImage>
          <InstallFrom>
            <MetaData wcm:action="add"><Key>/IMAGE/INDEX</Key><Value>{image_index}</Value></MetaData>
          </InstallFrom>
          <InstallTo><DiskID>0</DiskID><PartitionID>3</PartitionID></InstallTo>
        </OSImage>
      </ImageInstall>
      <UserData>
        <AcceptEula>true</AcceptEula>
        <FullName>homecloud</FullName>
        <Organization>homecloud</Organization>
      </UserData>
    </component>
  </settings>

  <settings pass="specialize">
    <component name="Microsoft-Windows-Shell-Setup" processorArchitecture="amd64" publicKeyToken="31bf3856ad364e35" language="neutral" versionScope="nonSxS">
      <ComputerName>{computer_name}</ComputerName>
      <TimeZone>{timezone}</TimeZone>
    </component>
    <component name="Microsoft-Windows-Deployment" processorArchitecture="amd64" publicKeyToken="31bf3856ad364e35" language="neutral" versionScope="nonSxS">
      <RunSynchronous>
        <!-- Client Windows ships with the built-in Administrator turned off. -->
        <RunSynchronousCommand wcm:action="add"><Order>1</Order><Path>net user Administrator /active:yes</Path></RunSynchronousCommand>
        <!-- No BitLocker device encryption: a lab VM has no use for a recovery key. -->
        <RunSynchronousCommand wcm:action="add"><Order>2</Order><Path>reg add HKLM\\SYSTEM\\CurrentControlSet\\Control\\BitLocker /v PreventDeviceEncryption /t REG_DWORD /d 1 /f</Path></RunSynchronousCommand>
      </RunSynchronous>
    </component>
    <component name="Microsoft-Windows-TerminalServices-LocalSessionManager" processorArchitecture="amd64" publicKeyToken="31bf3856ad364e35" language="neutral" versionScope="nonSxS">
      <fDenyTSConnections>false</fDenyTSConnections>
    </component>
    <component name="Networking-MPSSVC-Svc" processorArchitecture="amd64" publicKeyToken="31bf3856ad364e35" language="neutral" versionScope="nonSxS">
      <FirewallGroups>
        <FirewallGroup wcm:action="add" wcm:keyValue="RemoteDesktop">
          <Active>true</Active>
          <Group>Remote Desktop</Group>
          <Profile>all</Profile>
        </FirewallGroup>
      </FirewallGroups>
    </component>
  </settings>

  <settings pass="oobeSystem">
    <component name="Microsoft-Windows-Shell-Setup" processorArchitecture="amd64" publicKeyToken="31bf3856ad364e35" language="neutral" versionScope="nonSxS">
      <UserAccounts>
        <AdministratorPassword><Value>{password}</Value><PlainText>true</PlainText></AdministratorPassword>
      </UserAccounts>
      <!-- Log on once by itself, so the first-logon commands below run. -->
      <AutoLogon>
        <Enabled>true</Enabled>
        <LogonCount>1</LogonCount>
        <Username>Administrator</Username>
        <Password><Value>{password}</Value><PlainText>true</PlainText></Password>
      </AutoLogon>
      <FirstLogonCommands>
        <SynchronousCommand wcm:action="add"><Order>1</Order><CommandLine>{install_guest_tools}</CommandLine></SynchronousCommand>
        <!-- AutoLogon leaves the password in the registry; take it out. -->
        <SynchronousCommand wcm:action="add"><Order>2</Order><CommandLine>reg delete "HKLM\\SOFTWARE\\Microsoft\\Windows NT\\CurrentVersion\\Winlogon" /v DefaultPassword /f</CommandLine></SynchronousCommand>
        <SynchronousCommand wcm:action="add"><Order>3</Order><CommandLine>reg add "HKLM\\SOFTWARE\\Microsoft\\Windows NT\\CurrentVersion\\Winlogon" /v AutoAdminLogon /t REG_SZ /d 0 /f</CommandLine></SynchronousCommand>
        <!-- Don't leave Administrator signed in on the console. -->
        <SynchronousCommand wcm:action="add"><Order>4</Order><CommandLine>shutdown /l</CommandLine></SynchronousCommand>
      </FirstLogonCommands>
      <OOBE>
        <HideEULAPage>true</HideEULAPage>
        <HideOEMRegistrationScreen>true</HideOEMRegistrationScreen>
        <HideOnlineAccountScreens>true</HideOnlineAccountScreens>
        <HideLocalAccountScreen>true</HideLocalAccountScreen>
        <HideWirelessSetupInOOBE>true</HideWirelessSetupInOOBE>
        <ProtectYourPC>3</ProtectYourPC>
      </OOBE>
    </component>
  </settings>
</unattend>
"""


def autounattend(computer_name: str) -> str:
    return AUTOUNATTEND.format(
        computer_name=escape(computer_name.upper()),
        timezone=escape(config.WINDOWS_TIMEZONE),
        image_index=config.WINDOWS_IMAGE_INDEX,
        password=escape(config.WINDOWS_ADMIN_PASSWORD),
        install_guest_tools=escape(_INSTALL_GUEST_TOOLS),
    )


def windows_answer(computer_name: str) -> bytes:
    return _iso({"autounattend.xml": autounattend(computer_name)}, "UNATTEND")
